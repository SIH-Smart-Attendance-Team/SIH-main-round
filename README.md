# WeatherGPT Hybrid Helpline — Architecture & Integration Notes

## 1. Components

| Component | Tech | Role |
|---|---|---|
| Core Agent | FastAPI (Python) | Single source of truth for NLU, weather/disaster answers, and escalation decisions |
| Escalation Engine | Pure Python module (`escalation_engine.py`) | Rule + confidence hybrid; channel-agnostic |
| Session Store | Redis | Conversation state, turn counts, "pending human" flags |
| Voice Channel | Twilio Programmable Voice | Inbound number, speech capture, TTS, warm transfer via Conference |
| WhatsApp Channel | Meta WhatsApp Business Cloud API | Inbound/outbound text messages, agent handoff |
| Human Agent Routing | Static table for MVP → Twilio TaskRouter or a CRM queue for production | Skill-based routing (agri expert vs disaster officer vs general) |

## 2. Why one core agent, two adapters

Both webhooks (`voice_webhook.py`, `whatsapp_webhook.py`) call `CoreAgent.handle_turn()`.
This guarantees:
- Escalation criteria can't silently drift between channels.
- A farmer who starts on WhatsApp and later calls in gets consistent behavior.
- You only have to update NLU/intent logic in one place.

The only channel-specific code lives in the adapters: TwiML generation and
conference/whisper logic for voice; Graph API message sends and
pending-human suppression for WhatsApp.

## 3. Voice flow (Twilio)

1. `POST /voice/incoming` — greets caller, opens `<Gather input="speech">`.
2. `POST /voice/gather` — receives `SpeechResult`, calls `CoreAgent.handle_turn()`.
   - If `escalate=False`: speaks the reply, re-opens `<Gather>` for the next turn.
   - If `escalate=True`: tells the caller they're being connected, redirects to `/voice/transfer`.
3. `POST /voice/transfer` — puts the caller into a named Twilio `<Conference>`
   (`start_conference_on_enter=False`, so they wait with hold music), and
   fires an **outbound** REST API call to the routed human agent's number,
   pointing that leg at `/voice/whisper`.
4. `POST /voice/whisper` — plays a short context summary **only to the
   agent** ("Incoming escalation, reason: emergency_keyword_match..."),
   then joins them into the same conference (`start_conference_on_enter=True`),
   completing the warm transfer.

**Language handling:** `Gather language=` and `Say language=` are set per
turn from the detected/selected language. Twilio's native speech
recognition and `<Say>` voice coverage varies by Indian language — verify
current supported locales before committing to a launch list; for
languages Twilio doesn't cover well, proxy STT/TTS through Google Cloud
or Azure Cognitive Services instead of Twilio's built-in engines.

**Failure fallback:** if the human agent leg doesn't answer within N
seconds (configure a `timeout` on the outbound `calls.create`), the caller
should hear a fallback message with an alternate number/SMS callback
option — don't leave them in a conference indefinitely. Add a
status-callback on the outbound call to detect no-answer/busy and redirect
the caller's conference to a voicemail-style capture.

## 4. WhatsApp flow (Meta Cloud API)

1. `GET /whatsapp/webhook` — one-time verification handshake (`hub.challenge` echo).
2. `POST /whatsapp/webhook` — inbound message event (text or voice note). Extract `wa_id` and text/transcript.
3. If the thread is flagged `pending_human`, the bot stays silent (a human
   is already handling it via the same number/dashboard).
4. Otherwise, call `CoreAgent.handle_turn()`, send the reply via the Graph
   API `/messages` endpoint (`whatsapp_webhook.send_whatsapp_message`).
5. If escalation triggers, set the `pending_human` flag (TTL'd, e.g. 6h)
   and POST a notification to your internal agent dashboard/CRM/Slack
   webhook with the same `handoff_summary` used in the voice whisper.

**Implementation:** Meta's own **WhatsApp Cloud API** is the single supported
path (no third-party BSP required, free-tier friendly for
government/NGO-style deployments). Voice notes are transcribed via the
shared `voice_service` (Bhashini → Whisper fallback) before being passed to
the core agent. Outbound messages for alert broadcasting reuse the same
`send_whatsapp_message` function.

## 5. Escalation criteria (shared)

Implemented in `escalation_engine.py`, evaluated fresh on every turn:

1. **Emergency keyword match** (multilingual, life-safety terms) → `CRITICAL`, routed to disaster response.
2. **Explicit request for a human** → `MEDIUM`, general queue.
3. **Known complex/high-stakes intents** (crop disease diagnosis, pesticide dosage, livestock illness, etc.) → routed to an agriculture expert by design, not by model failure.
4. **Sustained low NLU/ASR confidence** (2+ consecutive turns below threshold) → the bot stops guessing and hands off.
5. **Distress sentiment** sustained past the first couple of turns → `HIGH`.
6. **Long unresolved threads** (turn count ceiling) → low-priority handoff so nobody loops with the bot forever.

Each decision carries a `handoff_summary` — a short, human-readable
context string reused for both the voice whisper and the WhatsApp agent
notification, so agents on either channel get the same quality of
context.

## 6. Things to harden before production

- **Keyword lists are a first line of defense, not a complete safety net.**
  Pair them with a proper classifier/LLM-based urgency scorer per language,
  and get native-speaker + domain-expert review of all trigger phrases.
- **Twilio TaskRouter** (or an equivalent skills-based queue) should
  replace the static `HUMAN_AGENT_ROUTING` dict — you need agent
  availability, shift schedules, and language-skill matching in practice.
- **Rate limiting & abuse protection** on both webhooks.
- **Audit logging** of every escalation decision (reason, queue, outcome)
  for compliance and for tuning thresholds over time.
- **Offline/degraded mode**: if Redis or the core NLU service is down,
  both channels should fail toward the *same* safe default (e.g. always
  escalate on any life-safety keyword hit, even if scoring is unavailable).
- **WhatsApp session windows**: Meta enforces a 24-hour customer-service
  window for free-form replies; outside it you need pre-approved template
  messages — relevant if a human agent needs to follow up after that window closes.
