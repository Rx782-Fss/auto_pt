"""邮件通知工具。"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any, Dict, List, Tuple

DEFAULT_SENDER_NAME = "Auto PT Downloader"
_VALID_TRANSPORT_MODES = {"ssl", "starttls", "plain"}
_NON_RETRIABLE_SMTP_EXCEPTIONS = (
    smtplib.SMTPAuthenticationError,
    smtplib.SMTPRecipientsRefused,
    smtplib.SMTPSenderRefused,
    smtplib.SMTPDataError,
)


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enable", "enabled"}
    return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def _split_recipients(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return []

    normalized = value.replace(";", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _normalize_transport_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in _VALID_TRANSPORT_MODES else ""


def _infer_transport_mode_from_port(smtp_port: int) -> str:
    if smtp_port in {587, 2525}:
        return "starttls"
    if smtp_port == 25:
        return "plain"
    return "ssl"


def _build_transport_mode_candidates(transport_mode: str, smtp_port: int) -> List[str]:
    """按当前配置和端口生成可尝试的 SMTP 传输模式。"""
    preferred_mode = _normalize_transport_mode(transport_mode)
    inferred_mode = _infer_transport_mode_from_port(smtp_port)

    candidates: List[str] = []
    if preferred_mode:
        candidates.append(preferred_mode)
    if inferred_mode not in candidates:
        candidates.append(inferred_mode)

    if smtp_port == 25:
        fallback_order = ("plain", "starttls", "ssl")
    elif smtp_port in {587, 2525}:
        fallback_order = ("starttls", "ssl")
    else:
        fallback_order = ("ssl", "starttls")

    for mode in fallback_order:
        if mode not in candidates:
            candidates.append(mode)

    return candidates


def _is_retryable_smtp_error(exc: Exception) -> bool:
    if isinstance(exc, _NON_RETRIABLE_SMTP_EXCEPTIONS):
        return False
    if isinstance(exc, (smtplib.SMTPException, ssl.SSLError, OSError, TimeoutError)):
        return True

    message = str(exc).lower()
    retryable_markers = (
        "unexpectedly closed",
        "connection reset",
        "connection aborted",
        "broken pipe",
        "tls",
        "ssl",
        "handshake",
        "eof occurred",
    )
    return any(marker in message for marker in retryable_markers)


def _describe_smtp_error(exc: Exception, smtp_port: int) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        code = getattr(exc, "smtp_code", "")
        return f"SMTP 登录失败{f'（{code}）' if code else ''}：请检查 SMTP 授权码 / 密码和发件账号是否匹配"

    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return "SMTP 服务器不支持当前加密方式，请尝试切换 SSL / STARTTLS / 明文"

    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return (
            "SMTP 连接在认证阶段被服务器断开，请检查 SMTP 服务是否已开启，"
            "以及端口 / 加密方式是否匹配"
        )

    if isinstance(exc, ssl.SSLError):
        return (
            "SMTP TLS 握手失败，请检查端口和加密方式是否匹配，"
            "以及服务器证书和系统时间是否正常"
        )

    if isinstance(exc, (ConnectionError, OSError, TimeoutError)):
        return f"SMTP 连接失败：{exc}"

    message = str(exc).strip()
    if "unexpectedly closed" in message.lower():
        return (
            "SMTP 连接在认证阶段被服务器断开，请检查 SMTP 服务是否已开启，"
            "以及端口 / 加密方式是否匹配"
        )

    if not message:
        return f"SMTP 发送失败（端口 {smtp_port}）"

    return message


def _send_via_transport(
    message: EmailMessage,
    transport_mode: str,
    smtp_host: str,
    smtp_port: int,
    username: str,
    password: str,
    timeout: int,
    ssl_context: ssl.SSLContext,
) -> None:
    if transport_mode == "ssl":
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout, context=ssl_context) as server:
            if username and password:
                server.login(username, password)
            server.send_message(message)
        return

    with smtplib.SMTP(smtp_host, smtp_port, timeout=timeout) as server:
        server.ehlo()
        if transport_mode == "starttls":
            server.starttls(context=ssl_context)
            server.ehlo()
        elif transport_mode != "plain":
            raise ValueError(f"不支持的邮件传输模式：{transport_mode}")

        if username and password:
            server.login(username, password)
        server.send_message(message)


def normalize_notification_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """归一化通知配置，便于 UI 与 SMTP 发送复用。"""
    if not isinstance(settings, dict):
        return {}

    normalized = dict(settings)
    smtp_host = str(normalized.get("smtp_host", "") or "").strip()
    sender_email = str(normalized.get("sender_email", "") or "").strip()
    sender_name = str(normalized.get("sender_name", "") or "").strip()
    smtp_username = str(normalized.get("smtp_username", "") or "").strip()
    smtp_password = str(normalized.get("smtp_password", "") or "")
    recipient_email = str(normalized.get("recipient_email", "") or "").strip()
    smtp_port = _to_int(normalized.get("smtp_port"), 0)
    transport_mode = _normalize_transport_mode(normalized.get("transport_mode", ""))
    if not transport_mode:
        transport_mode = _infer_transport_mode_from_port(smtp_port)
    legacy_enabled = _to_bool(normalized.get("enabled", False))
    has_new_flags = "download_start_enabled" in normalized or "download_complete_enabled" in normalized
    if has_new_flags:
        download_start_enabled = _to_bool(normalized.get("download_start_enabled", legacy_enabled))
        download_complete_enabled = _to_bool(normalized.get("download_complete_enabled", legacy_enabled))
    else:
        download_start_enabled = legacy_enabled
        download_complete_enabled = legacy_enabled

    normalized.update({
        "enabled": download_start_enabled or download_complete_enabled,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "transport_mode": transport_mode,
        "sender_email": sender_email,
        "sender_name": sender_name,
        "smtp_username": smtp_username,
        "smtp_password": smtp_password,
        "recipient_email": recipient_email,
        "download_start_enabled": download_start_enabled,
        "download_complete_enabled": download_complete_enabled,
    })

    if not normalized["smtp_port"]:
        normalized["smtp_port"] = {
            "ssl": 465,
            "starttls": 587,
            "plain": 25,
        }[transport_mode]

    if not normalized["smtp_username"]:
        normalized["smtp_username"] = normalized["sender_email"]

    return normalized


def notification_settings_complete(settings: Dict[str, Any]) -> bool:
    """判断邮件通知配置是否足以发送邮件。"""
    normalized = normalize_notification_settings(settings)
    return all([
        normalized.get("smtp_host"),
        normalized.get("smtp_port"),
        normalized.get("sender_email"),
        normalized.get("recipient_email"),
        normalized.get("smtp_password"),
    ])


def _build_message(settings: Dict[str, Any], subject: str, text: str, html: str | None = None) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((
        settings.get("sender_name") or DEFAULT_SENDER_NAME,
        settings.get("sender_email") or settings.get("smtp_username") or "",
    ))
    recipients = _split_recipients(settings.get("recipient_email", ""))
    message["To"] = ", ".join(recipients)
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def send_email_notification(
    settings: Dict[str, Any],
    subject: str,
    text: str,
    html: str | None = None,
    timeout: int = 20,
    require_enabled: bool = False,
) -> Tuple[bool, str]:
    """发送邮件通知。"""
    normalized = normalize_notification_settings(settings)

    if require_enabled and not normalized.get("enabled", False):
        return False, "邮件通知未启用"

    if not notification_settings_complete(normalized):
        return False, "邮件通知配置不完整"

    recipients = _split_recipients(normalized.get("recipient_email", ""))
    if not recipients:
        return False, "收件邮箱不能为空"

    message = _build_message(normalized, subject, text, html)
    transport_mode = normalized.get("transport_mode", "ssl")
    smtp_host = normalized.get("smtp_host", "")
    smtp_port = _to_int(normalized.get("smtp_port"), 0)
    username = normalized.get("smtp_username") or normalized.get("sender_email")
    password = normalized.get("smtp_password", "")
    transport_candidates = _build_transport_mode_candidates(transport_mode, smtp_port)

    ssl_context = ssl.create_default_context()

    last_error: Exception | None = None
    for index, candidate_mode in enumerate(transport_candidates):
        try:
            _send_via_transport(
                message,
                candidate_mode,
                smtp_host,
                smtp_port,
                username,
                password,
                timeout,
                ssl_context,
            )
            return True, "邮件已发送"
        except Exception as exc:
            last_error = exc
            if not _is_retryable_smtp_error(exc) or index == len(transport_candidates) - 1:
                break

    if last_error is None:
        return False, "邮件发送失败：未知错误"

    return False, f"邮件发送失败：{_describe_smtp_error(last_error, smtp_port)}"
