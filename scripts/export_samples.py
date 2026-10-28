"""仅供离线/HTTP 验收的合成样本，不是观测记录。"""

from datetime import UTC, datetime

from astroagent.analysis import analyze_sources
from astroagent.gaia import GAIA_UNITS, build_adql
from astroagent.schemas import (
    ChatResponse,
    GaiaQuery,
    GaiaQueryResult,
    GaiaSourceData,
    LiteratureSearchResult,
    ObjectData,
    PaperData,
    QueryResult,
    Source,
)


def synthetic_request(count=100):
    date = datetime(2026, 10, 28, tzinfo=UTC)
    simbad = Source(url="https://example.invalid/synthetic-simbad", retrieved_at=date)
    ads = Source(name="ADS", url="https://example.invalid/synthetic-ads", retrieved_at=date)
    gaia = Source(name="Gaia", url="https://gea.esac.esa.int/archive/", retrieved_at=date)
    query = GaiaQuery(
        mode="cone", ra_deg=56.75, dec_deg=24.12, radius_arcmin=5, limit=100, estimate_distance=True
    )
    rows = [
        GaiaSourceData(
            source_id=str(5853498713190525696 + i),
            ra=56.75,
            dec=24.12,
            ref_epoch=2016,
            parallax=(i - 5) / 2 if i != 2 else None,
            parallax_error=0.1,
            pmra=-20 + i / 3 if i != 1 else None,
            pmdec=45 - i / 5,
            bp_rp=0.1 + i / 100 if i != 3 else None,
            phot_g_mean_mag=8 + i / 20,
            separation_arcsec=float(i),
        )
        for i in range(count)
    ]
    adql, maxrec = build_adql(query)
    response = ChatResponse(
        status="success",
        answer="合成测试数据，不是实际观测。",
        results=[
            QueryResult(
                object_name="合成天体",
                status="success",
                source=simbad,
                data=ObjectData(main_id='=测试,"合成"\n第二行', dec_deg=-20),
            )
        ],
        literature_results=[
            LiteratureSearchResult(
                query="synthetic",
                rows=1,
                start=0,
                sort="relevance",
                status="success",
                total_found=1,
                returned_count=1,
                has_more=False,
                source=ads,
                papers=[
                    PaperData(
                        bibcode="synthetic",
                        title="合成论文",
                        authors=["甲", "乙"],
                        doi=["10.synthetic/example"],
                        abstract="@合成摘要",
                        source=ads,
                    )
                ],
            )
        ],
        gaia_results=[
            GaiaQueryResult(
                query=query.effective_parameters(),
                adql=adql,
                maxrec=maxrec,
                status="success",
                returned_count=count,
                has_more=True,
                truncated=True,
                archive_overflow=False,
                data=rows,
                analysis=analyze_sources(rows, query, truncated=True),
                units=GAIA_UNITS,
                source=gaia,
                warnings=["合成样本；截断仅供测试"],
            )
        ],
        sources=[simbad, ads, gaia],
    )
    return {
        "schema_version": "1",
        "snapshot": response.model_dump(mode="json"),
        "plots": [
            {"gaia_result_index": 0, "kind": kind}
            for kind in ("proper_motion", "parallax_histogram", "observed_cmd")
        ],
    }
