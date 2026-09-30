"""AgentManager — 只读 Agent 列表查询，供 agents:request 使用。"""
import json, logging, os, subprocess, threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
_file_locks: Dict[str, threading.Lock] = {}
_lock = threading.Lock()

def _get_lock(path: str) -> threading.Lock:
    with _lock:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]


# hermes status 平台显示名 → 前端通道 key 映射
# hermes status 的 "Messaging Platforms" 段用显示名（如 Feishu/Weixin/WeCom/QQBot），
# 前端 CHANNEL_LABELS 用 openclaw 通道 key（如 feishu/openclaw-weixin/wecom-bot-long/qqbot），需转换
_PLATFORM_LABEL_TO_CHANNEL_KEY: Dict[str, str] = {
    "Telegram": "telegram",
    "Discord": "discord",
    "WhatsApp": "whatsapp",
    "Signal": "signal",
    "Slack": "slack",
    "Email": "email",
    "SMS": "sms",
    "DingTalk": "dingtalk-connector",
    "Feishu": "feishu",
    "WeCom": "wecom-bot-long",
    "WeCom Callback": "wecom-bot",
    "Weixin": "openclaw-weixin",
    "BlueBubbles": "bluebubbles",
    "QQBot": "qqbot",
    "Yuanbao": "yuanbao",
    "LightClawBot": "lightclawbot",
}


def _map_platform_label_to_channel_key(label: str) -> str:
    """把 hermes status 的平台显示名映射为前端通道 key。

    未在映射表中的名称原样返回（小写化），由前端兜底处理。
    """
    return _PLATFORM_LABEL_TO_CHANNEL_KEY.get(label, label.lower())


class AgentManager:
    DEFAULT = [{"id":"main","name":"main","identity":{"name":"默认助手","emoji":"🤖"}}]

    def __init__(self, sessions_dir: str):
        self._path = os.path.join(sessions_dir, "agents.json")
        self._lock = _get_lock(self._path)

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                agents = data.get("agents") if isinstance(data, dict) else data
                if isinstance(agents, list):
                    # 注入 soulId（从 lightsoul config 读取）
                    self._inject_soul_ids(agents)
                    # 注入 channel（hermes 仅 lightclawbot 单通道，所有 agent 均绑定）
                    self._inject_channels(agents)
                    return agents
            except FileNotFoundError:
                pass
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("[agent_manager] read %s: %s", self._path, e)
            agents = [dict(a) for a in self.DEFAULT]
            self._inject_soul_ids(agents)
            self._inject_channels(agents)
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            t = self._path + ".tmp"
            try:
                with open(t, "w", encoding="utf-8") as f:
                    json.dump({"agents": agents}, f, ensure_ascii=False, indent=2)
                    f.flush(); os.fsync(f.fileno())
                os.replace(t, self._path)
                logger.info("[agent_manager] init %s", self._path)
            except OSError: pass
            return agents

    def _inject_channels(self, agents: List[Dict[str, Any]]) -> None:
        """为每个 agent 注入 model 和 channel 字段（管理视图 AgentCard 展示用）。

        hermes 不支持 agent 级单独配置，所有 agent 共用同一套 model 和 channel：
        - model：~/.hermes/config.yaml 的 model.provider/default（主模型）
        - channel：hermes status 的 Messaging Platforms 段，已配置通道 key 列表，'|' 拼接

        语义（对齐前端 AgentCard 三态展示）：
        - model 和 channel **必须成对写入**：读取失败或未配置一律写空字符串 ''，
          让前端知道"插件支持查询但当前未配置"（显示「配置」按钮），
          与"插件不支持查询"（字段 key 不存在，前端显示「查询失败」）区分。
        - 已有非空值的字段不覆盖（兼容上层显式注入）。
        """
        model, channel = self._read_hermes_model_channel()
        for a in agents:
            if not a.get("model"):
                a["model"] = model or ""
            if not a.get("channel"):
                a["channel"] = channel or ""

    def _read_hermes_model_channel(self) -> tuple[Optional[str], Optional[str]]:
        """读取 hermes 实例的 model 和 channel。

        返回 (model, channel)：
        - model：~/.hermes/config.yaml 的 model.provider + model.default（主模型，所有 agent 共用）
        - channel：hermes status 的 Messaging Platforms 段，已配置通道 key 列表，'|' 拼接

        hermes-lightclaw 插件运行在 hermes venv，可直接 import yaml（hermes 框架依赖）。
        任何异常都返回 (None, None)，不阻塞 agents 列表返回。
        """
        model: Optional[str] = None
        channel: Optional[str] = None
        try:
            model = self._read_model_from_config()
        except Exception as e:
            logger.debug("[agent_manager] read hermes model failed: %s", e)

        try:
            channel = self._read_channels_from_status()
        except Exception as e:
            logger.debug("[agent_manager] read hermes channel failed: %s", e)

        return model, channel

    def _read_model_from_config(self) -> Optional[str]:
        """从 ~/.hermes/config.yaml 读取主模型（provider/model）。

        实际配置结构（与前端 acli 解析一致）：
            model:
              default: hy3-preview      # 模型名
              provider: tencent_hy_token_plan  # provider 名
            providers:
              <provider>:
                model_display_name: Hy3 preview  # 可选展示名
        返回 "provider/model" 形式；缺失返回 None。
        """
        hermes_home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
        path = os.path.join(hermes_home, "config.yaml")
        if not os.path.isfile(path):
            return None
        # hermes-lightclaw 运行在 hermes venv，yaml 是 hermes 框架依赖可直接 import
        import yaml  # type: ignore[import-untyped]
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        if not isinstance(config, dict):
            return None
        model_cfg = config.get("model")
        if not isinstance(model_cfg, dict):
            return None
        # 模型名：优先 default（hermes 实际字段），兼容 name（官方文档示例）
        model_name = model_cfg.get("default") or model_cfg.get("name")
        if not model_name:
            return None
        provider = model_cfg.get("provider")
        return f"{provider}/{model_name}" if provider else str(model_name)

    def _read_channels_from_status(self) -> Optional[str]:
        """调用 `hermes status` 解析已配置的通道 key 列表（'|' 拼接）。

        与官方 CLI 对齐：hermes status 的 "Messaging Platforms" 段输出每个平台
        的配置状态（✓ configured / ✗ not configured）。只收集 configured 的平台。

        输出示例：
            ◆ Messaging Platforms
              Telegram      ✗ not configured
              Feishu        ✓ configured (home: ou_xxx)
              Weixin        ✓ configured (home: o9cqxxx)
              QQBot         ✗ not configured

        platform 名经 _map_platform_label_to_channel_key 映射为前端通道 key。
        hermes status 不可用或解析失败返回 None。
        """
        output = self._run_hermes_cli(["status"])
        if not output:
            return None
        keys: List[str] = []
        in_messaging = False
        for line in output.splitlines():
            s = line.strip()
            if not s:
                continue
            # 进入 Messaging Platforms 段
            if s.startswith("◆ Messaging Platforms"):
                in_messaging = True
                continue
            # 遇到下一个段（◆ 开头）结束
            if in_messaging and s.startswith("◆"):
                break
            if not in_messaging:
                continue
            # 匹配 "<Platform>  ✓ configured" 行（✗ not configured 跳过）
            if "✓" not in s and "configured" not in s.lower():
                continue
            if "not configured" in s.lower():
                continue
            # 提取平台名（行首到第一个连续空格/✗/✓ 之前）
            # 例： "Feishu        ✓ configured (home: ou_xxx)" → "Feishu"
            # 例： "WeCom Callback  ✗ not configured" → "WeCom Callback"
            name_part = s.split("✓")[0].strip()
            if not name_part:
                continue
            mapped = _map_platform_label_to_channel_key(name_part)
            if mapped and mapped not in keys:
                keys.append(mapped)
        return "|".join(keys) if keys else None

    def _run_hermes_cli(self, args: List[str]) -> Optional[str]:
        """执行 hermes CLI 命令并返回 stdout（失败返回 None）。

        hermes 二进制路径按以下顺序探测：PATH / ~/.hermes/hermes-agent/venv/bin/hermes。
        超时 10s，避免阻塞 agents 请求。
        """
        candidates: List[str] = ["hermes"]
        hermes_home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
        candidates.append(os.path.join(hermes_home, "hermes-agent", "venv", "bin", "hermes"))
        for bin_path in candidates:
            try:
                result = subprocess.run(
                    [bin_path] + args,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    return result.stdout
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                continue
        return None

    def _inject_soul_ids(self, agents: List[Dict[str, Any]]) -> None:
        """从 lightsoul config 读取 agentId→soulId 映射，注入到 agent 条目。

        hermes_soul.sh 默认写入 $HOME/.config/lightsoul/config.json（XDG 标准路径），
        因此必须从同一路径读取，不能用 ~/.hermes/.config/lightsoul/config.json（hermes 旧路径）。
        """
        # hermes_soul.sh 默认写入路径（$HOME/.config/lightsoul/config.json）
        home = os.path.expanduser("~")
        ls_config = os.path.join(home, ".config", "lightsoul", "config.json")
        if not os.path.exists(ls_config):
            return
        try:
            with open(ls_config, "r", encoding="utf-8") as f:
                soul_map = json.load(f)
            if not isinstance(soul_map, dict):
                return
            for a in agents:
                sid = soul_map.get(a.get("id", ""))
                if sid:
                    a["soulId"] = sid
        except Exception:
            pass
