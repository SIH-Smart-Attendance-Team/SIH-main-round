from fastapi import APIRouter
from typing import List
from backend.app.models.data_source import DataSource, DataLink

router = APIRouter(prefix="/data-sources", tags=["Data Sources"])

DATA_SOURCES = [
    DataSource(
        label="Numerical Ocean Model Outputs",
        links=[
            DataLink(text="INCOIS LAS", url="https://las.incois.gov.in/"),
            DataLink(
                text="Copernicus Marine (GLOBAL_MULTIYEAR_PHY_001_030)",
                url="https://data.marine.copernicus.eu/product/GLOBAL_MULTIYEAR_PHY_001_030/description",
            ),
        ],
    ),
    DataSource(
        label="Argo Global Data",
        links=[
            DataLink(
                text="Ifremer Argo FTP",
                url="ftp://ftp.ifremer.fr/ifremer/argo",
                is_ftp=True,
            )
        ],
    ),
    DataSource(
        label="Glider Data",
        links=[
            DataLink(
                text="Ifremer Glider FTP",
                url="ftp://ftp.ifremer.fr/ifremer/glider/v2/",
                is_ftp=True,
            )
        ],
    ),
    DataSource(
        label="Collection of In-situ Data",
        links=[],
        note="Link not yet provided — add when available",
    ),
]


@router.get("/", response_model=List[DataSource])
def get_data_sources():
    return DATA_SOURCES
