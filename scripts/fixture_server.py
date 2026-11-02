"""仅用于离线验收的合成模型/工具服务；普通应用入口不导入本模块。"""

import json
import os
import re
import time
from uuid import uuid4

from langchain_core.messages import AIMessage

import astroagent.main as main
import astroagent.services as services
from astroagent.agent import AstroAgent
from astroagent.api import conversations, projects, workflows
from astroagent.config import Settings
from astroagent.conversations import ConversationRepository
from astroagent.main import app as app
from scripts.legacy_fixture_storage import compose
from scripts.synthetic_services import SyntheticAds, SyntheticGaia, SyntheticSimbad

# Explicit old-contract fixture, not a PostgreSQL runtime acceptance server.
# Never inherit an operator's daily database connection from .env.

os.environ["ASTROAGENT_DATABASE_URL"] = ""
main.PostgresRepository = ConversationRepository
services.compose = compose


class SyntheticModel:
    def invoke(self, messages):
        message = next(m.content for m in reversed(messages) if m.type == "human")
        if "__fail_model__" in message:
            raise TimeoutError("synthetic")
        if messages[-1].type == "tool":
            return AIMessage(
                content="合成验收结果已返回。请在右侧核查完整测量、单位和查询条件；这些不是实际观测。"
            )
        if "__wait__" in message:
            time.sleep(10)
        history = []
        for m in messages:
            if m.type == "human" and m.content.startswith("历史数据（非本轮查询）：\n"):
                history = json.loads(m.content.split("\n", 1)[1])
        if any(word in message for word in ("解释", "DOI", "第二篇", "第一篇")):
            return AIMessage(
                content="根据已保存的历史轮次解释；本轮未执行新数据库查询。合成样本中的近似距离有条件，不能当作直接测量。"
            )
        if "ADS" in message or "文献" in message or "论文" in message:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_ads",
                        "args": {
                            "query": "__wait_project__"
                            if "__wait_project__" in message
                            else "synthetic",
                            "rows": 1,
                        },
                        "id": str(uuid4()),
                    }
                ],
            )
        if "SIMBAD" in message and "Gaia" not in message:
            return AIMessage(
                content="",
                tool_calls=[
                    {"name": "query_simbad", "args": {"object_name": "M45"}, "id": str(uuid4())}
                ],
            )
        identifier = re.search(r"\b[1-9][0-9]{15,18}\b", message)
        query = (
            {"mode": "source_id", "source_id": identifier.group()}
            if identifier
            else {
                "mode": "cone",
                "ra_deg": 56.75,
                "dec_deg": 24.12,
                "radius_arcmin": 5,
                "limit": 100,
            }
        )
        if "RUWE" in message.upper():
            candidates = [
                r
                for h in history
                for r in h["historical_response"]["gaia_results"]
                if r["query"]["mode"] == "cone"
            ]
            if not candidates:
                return AIMessage(content="请先提供要调整的视场条件。")
            query = dict(candidates[-1]["query"])
            query["ruwe_max"] = 1.4
        return AIMessage(
            content="", tool_calls=[{"name": "query_gaia", "args": query, "id": str(uuid4())}]
        )


def fixture_agent():
    return AstroAgent(
        SyntheticModel(),
        SyntheticSimbad(),
        Settings(_env_file=None, deepseek_api_key=""),
        SyntheticAds(),
        SyntheticGaia(),
    )


conversations.get_agent = fixture_agent


def fixture_executor():
    from astroagent.schemas import GaiaQuery, LiteratureQuery

    def execute(family, parameters):
        if "__wait_project__" in json.dumps(parameters):
            time.sleep(20)
        if family == "simbad":
            return SyntheticSimbad().query(parameters["object_name"])
        if family == "ads":
            return SyntheticAds().search(LiteratureQuery(**parameters))
        return SyntheticGaia().query(GaiaQuery(**parameters))

    return execute


projects.get_executor = fixture_executor
workflows.get_executor = fixture_executor
