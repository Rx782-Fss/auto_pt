import atexit
import base64
import copy
import os
import time
import shutil
import tempfile
import unittest
import smtplib
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

_TEST_RUNTIME_DIR = Path(tempfile.mkdtemp(prefix="auto_pt_test_runtime_"))
_TEST_LOG_DIR = _TEST_RUNTIME_DIR / "logs"
_TEST_CONFIG_FILE = _TEST_RUNTIME_DIR / "config.yaml"
_TEST_KEY_FILE = _TEST_RUNTIME_DIR / "auto_pt.key"
_TEST_LOG_DIR.mkdir(parents=True, exist_ok=True)

os.environ["AUTO_PT_LOG_DIR"] = str(_TEST_LOG_DIR)
os.environ["AUTO_PT_CONFIG_FILE"] = str(_TEST_CONFIG_FILE)
os.environ["AUTO_PT_KEY_FILE"] = str(_TEST_KEY_FILE)

atexit.register(lambda: shutil.rmtree(_TEST_RUNTIME_DIR, ignore_errors=True))

import web
import src.crypto_config as crypto_config
import src.notifications as notifications
from src.config import Config
from src.mteam import MTeamClient
from src.history import DownloadHistory
import src.qbittorrent as qb_module
from src.qbittorrent import QBittorrentClient
import src.runner as runner
from src.qb_status import qb_state_to_status

try:
    from cryptography.fernet import Fernet
except ImportError:  # pragma: no cover - 依赖缺失时跳过密钥相关测试
    Fernet = None


class AttrDict(dict):
    __getattr__ = dict.get


class FakeConfig:
    def __init__(self, sites):
        self.pt_sites = sites

    def get_site_by_name(self, name):
        for site in self.pt_sites:
            if site.get("name") == name:
                return site
        return None

    def get_enabled_sites(self):
        return [site for site in self.pt_sites if site.get("enabled", True)]


class CryptoConfigRegressionTests(unittest.TestCase):
    def setUp(self):
        if not crypto_config.CRYPTO_AVAILABLE or Fernet is None:
            self.skipTest("cryptography 未安装，跳过密钥持久化测试")

    def test_has_key_file_detects_legacy_root_key_when_env_path_is_used(self):
        with tempfile.TemporaryDirectory(prefix="auto_pt_key_") as temp_dir:
            base_dir = Path(temp_dir)
            legacy_key_file = base_dir / "auto_pt.key"
            target_key_file = base_dir / "data" / "auto_pt.key"
            legacy_key = Fernet.generate_key()
            legacy_key_file.write_bytes(base64.urlsafe_b64encode(legacy_key))

            with patch.object(crypto_config, "BASE_DIR", base_dir), patch.dict(
                os.environ,
                {"AUTO_PT_KEY_FILE": str(target_key_file)},
                clear=False,
            ):
                self.assertTrue(crypto_config.has_key_file())

    def test_get_key_migrates_legacy_root_key_to_persisted_path(self):
        with tempfile.TemporaryDirectory(prefix="auto_pt_key_") as temp_dir:
            base_dir = Path(temp_dir)
            legacy_key_file = base_dir / "auto_pt.key"
            target_key_file = base_dir / "data" / "auto_pt.key"
            legacy_key = Fernet.generate_key()
            legacy_key_file.write_bytes(base64.urlsafe_b64encode(legacy_key))

            with patch.object(crypto_config, "BASE_DIR", base_dir), patch.dict(
                os.environ,
                {"AUTO_PT_KEY_FILE": str(target_key_file)},
                clear=False,
            ):
                resolved_path = crypto_config._resolve_key_file()
                key = crypto_config._get_key()

            self.assertEqual(resolved_path, target_key_file)
            self.assertEqual(key, legacy_key)
            self.assertTrue(target_key_file.exists())
            self.assertEqual(target_key_file.read_bytes(), legacy_key_file.read_bytes())


class ConfigApiRegressionTests(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()
        self.auth_patches = [
            patch.object(web, "_is_first_time_setup", return_value=False),
            patch.object(web, "check_access_control", return_value=(True, None)),
            patch.object(web, "get_app_secret", return_value="test-secret"),
            patch.object(web, "reload_logging", return_value=None),
        ]
        for current_patch in self.auth_patches:
            current_patch.start()
        with web._session_tokens_lock:
            web._session_tokens.clear()
        self.addCleanup(self._stop_auth_patches)
        self.addCleanup(self._clear_session_tokens)

    def _stop_auth_patches(self):
        for current_patch in reversed(self.auth_patches):
            current_patch.stop()

    def _clear_session_tokens(self):
        with web._session_tokens_lock:
            web._session_tokens.clear()

    def _base_config(self, secret="test-secret"):
        return {
            "app": {
                "secret": secret,
                "access_control": "whitelist",
                "allowed_ips": ["192.168.1.24"],
                "web_port": 5000,
            },
            "qbittorrent": {
                "host": "http://127.0.0.1:8080",
                "username": "admin",
                "password": "secret-password",
                "save_path": "",
                "category": "",
            },
            "schedule": {"enabled": True, "interval": 300},
            "pt_sites": [
                {
                    "name": "hdtime",
                    "type": "mteam",
                    "base_url": "https://hdtime.org",
                    "rss_url": "https://hdtime.org/torrentrss.php?passkey=abc",
                    "passkey": "abc",
                    "uid": "",
                    "enabled": False,
                    "filter": {
                        "keywords": ["keep-me"],
                        "exclude": [],
                        "min_size": 0,
                        "max_size": 0,
                    },
                    "schedule": {"interval": 3600, "cleanup_interval": 7200},
                    "download_settings": {
                        "auto_download": False,
                        "auto_delete": False,
                        "delete_files": False,
                        "paused": False,
                    },
                    "tags": ["hdtime", "auto_pt"],
                }
            ],
        }

    def test_post_config_preserves_site_details_from_safe_payload(self):
        old_config = self._base_config()
        safe_payload = web.filter_sensitive_config(copy.deepcopy(old_config), include_secret=True)
        saved_state = {"config": copy.deepcopy(old_config)}

        def fake_load_config():
            return copy.deepcopy(saved_state["config"])

        def fake_save_config(config):
            saved_state["config"] = copy.deepcopy(config)

        with patch.object(web, "load_config", side_effect=fake_load_config), patch.object(
            web, "save_config", side_effect=fake_save_config
        ):
            response = self.client.post(
                "/api/config",
                json=safe_payload,
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])

        saved_site = saved_state["config"]["pt_sites"][0]
        self.assertEqual(saved_site["rss_url"], old_config["pt_sites"][0]["rss_url"])
        self.assertEqual(saved_site["passkey"], old_config["pt_sites"][0]["passkey"])
        self.assertEqual(saved_site["filter"], old_config["pt_sites"][0]["filter"])
        self.assertEqual(saved_site["tags"], old_config["pt_sites"][0]["tags"])
        self.assertEqual(saved_state["config"]["qbittorrent"]["password"], "secret-password")

    def test_get_config_does_not_expose_secret_but_keeps_auth_state(self):
        with patch.object(web, "load_config", return_value=self._base_config()):
            response = self.client.get(
                "/api/config",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertNotIn("secret", payload["config"]["app"])
        self.assertTrue(payload["config"]["app"]["auth_configured"])
        self.assertIn("logging", payload["config"])
        self.assertEqual(payload["config"]["logging"]["level"], "INFO")
        self.assertEqual(payload["config"]["log_level"], "INFO")
        self.assertTrue(payload["config"]["qbittorrent"]["configured"])
        self.assertNotIn("password", payload["config"]["qbittorrent"])

    def test_qb_test_uses_saved_password_when_request_password_is_blank(self):
        saved_config = self._base_config()

        with patch.object(web, "load_config", return_value=copy.deepcopy(saved_config)), patch(
            "src.qbittorrent.QBittorrentClient"
        ) as mock_qb_cls:
            qb_instance = mock_qb_cls.return_value
            qb_instance.get_version.return_value = "4.6.0"

            response = self.client.post(
                "/api/qb/test",
                json={
                    "host": "http://127.0.0.1:8080",
                    "username": "admin",
                    "password": "",
                },
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        mock_qb_cls.assert_called_once_with(
            host="http://127.0.0.1:8080",
            username="admin",
            password="secret-password",
        )

    def test_post_config_syncs_logging_level_fields(self):
        old_config = self._base_config()
        old_config["logging"] = {
            "level": "INFO",
            "suppress_request_logs": True,
            "request_log_level": "WARNING",
        }
        old_config["log_level"] = "INFO"
        safe_payload = web.filter_sensitive_config(copy.deepcopy(old_config), include_secret=True)
        safe_payload["logging"]["level"] = "DEBUG"
        safe_payload["log_level"] = "DEBUG"
        saved_state = {"config": copy.deepcopy(old_config)}

        def fake_load_config():
            return copy.deepcopy(saved_state["config"])

        def fake_save_config(config):
            saved_state["config"] = copy.deepcopy(config)

        with patch.object(web, "load_config", side_effect=fake_load_config), patch.object(
            web, "save_config", side_effect=fake_save_config
        ):
            response = self.client.post(
                "/api/config",
                json=safe_payload,
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(saved_state["config"]["logging"]["level"], "DEBUG")
        self.assertEqual(saved_state["config"]["log_level"], "DEBUG")

    def test_exchange_auth_token_issues_session_token(self):
        with patch.object(web, "load_config", return_value=self._base_config()):
            response = self.client.post(
                "/api/auth/token",
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["token_type"], "session")
        self.assertTrue(payload["token"])
        self.assertGreater(payload["expires_at"], 0)

    def test_session_token_can_access_config(self):
        with patch.object(web, "load_config", return_value=self._base_config()):
            auth_response = self.client.post(
                "/api/auth/token",
                headers={"Authorization": "Bearer test-secret"},
            )
            session_token = auth_response.get_json()["token"]
            response = self.client.get(
                "/api/config",
                headers={"Authorization": f"Bearer {session_token}"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertNotIn("secret", payload["config"]["app"])

    def test_session_token_persists_after_restart_reload(self):
        with tempfile.TemporaryDirectory(prefix="auto_pt_auth_tokens_") as temp_dir:
            token_file = Path(temp_dir) / "session_tokens.json"
            with patch.object(web, "_SESSION_TOKENS_FILE", token_file), patch.object(
                web, "load_config", return_value=self._base_config()
            ):
                with web._session_tokens_lock:
                    web._session_tokens.clear()

                auth_response = self.client.post(
                    "/api/auth/token",
                    headers={"Authorization": "Bearer test-secret"},
                )
                self.assertEqual(auth_response.status_code, 200)
                session_token = auth_response.get_json()["token"]

                with web._session_tokens_lock:
                    web._session_tokens.clear()

                web._load_session_tokens_from_disk()

                response = self.client.get(
                    "/api/config",
                    headers={"Authorization": f"Bearer {session_token}"},
                )

            self.assertTrue(token_file.exists())
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["success"])
            self.assertNotIn("secret", payload["config"]["app"])

    def test_validate_session_token_throttles_persistence_writes(self):
        original_last_persist = web._session_tokens_last_persist_at
        try:
            with web._session_tokens_lock:
                web._session_tokens.clear()
                web._session_tokens["session-token"] = int(time.time()) + 3600
                web._session_tokens_last_persist_at = time.time()

            with patch.object(web.os, "replace") as mock_replace:
                self.assertTrue(web._validate_session_token("session-token"))

            mock_replace.assert_not_called()
        finally:
            web._session_tokens_last_persist_at = original_last_persist

    def test_first_time_setup_allows_config_but_blocks_sensitive_routes(self):
        with patch.object(web, "_is_first_time_setup", return_value=True), patch.object(
            web, "load_config", return_value=self._base_config(secret="")
        ):
            config_response = self.client.get("/api/config")
            history_response = self.client.get("/api/history")
            config_file_response = self.client.get("/api/config/file")

        self.assertEqual(config_response.status_code, 200)
        config_payload = config_response.get_json()
        self.assertTrue(config_payload["success"])
        self.assertFalse(config_payload["config"]["app"]["auth_configured"])
        self.assertNotIn("secret", config_payload["config"]["app"])

        self.assertEqual(history_response.status_code, 403)
        self.assertEqual(history_response.get_json()["error"], "请先设置 API 认证密钥")

        self.assertEqual(config_file_response.status_code, 403)
        self.assertEqual(config_file_response.get_json()["error"], "请先设置 API 认证密钥")

    def test_save_config_invalidates_old_session_tokens_when_secret_changes(self):
        with web._session_tokens_lock:
            web._session_tokens["old-session-token"] = int(time.time()) + 3600

        saved_state = {"config": self._base_config()}

        def fake_load_config():
            return copy.deepcopy(saved_state["config"])

        def fake_save_config(config):
            saved_state["config"] = copy.deepcopy(config)

        with patch.object(web, "load_config", side_effect=fake_load_config), patch.object(
            web, "save_config", side_effect=fake_save_config
        ):
            response = self.client.post(
                "/api/config",
                json={"app": {"secret": "new-secret"}},
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertIn("auth", payload)
        self.assertEqual(payload["auth"]["token_type"], "session")
        self.assertTrue(payload["auth"]["session_token"])
        self.assertNotIn("old-session-token", web._session_tokens)
        self.assertIn(payload["auth"]["session_token"], web._session_tokens)

    def test_save_config_strips_runtime_only_fields_before_persisting(self):
        config_payload = {
            "app": {
                "secret": "test-secret",
                "auth_configured": True,
                "access_control": "lan",
                "allowed_ips": [],
                "web_port": 5000,
            },
            "auth": {"session_token": "temp-token"},
        }

        with patch("src.config.save_config") as mock_persist:
            web.save_config(config_payload)

        persisted_config = mock_persist.call_args.args[0]
        self.assertNotIn("auth", persisted_config)
        self.assertNotIn("auth_configured", persisted_config["app"])

    def test_first_time_save_returns_recovery_code(self):
        saved_state = {"config": self._base_config(secret="")}

        def fake_load_config():
            return copy.deepcopy(saved_state["config"])

        def fake_save_config(config):
            saved_state["config"] = copy.deepcopy(config)

        with patch.object(web, "_is_first_time_setup", return_value=True), patch.object(
            web, "load_config", side_effect=fake_load_config
        ), patch.object(web, "save_config", side_effect=fake_save_config):
            response = self.client.post(
                "/api/config",
                json={"app": {"secret": "new-secret"}},
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["recovery_code"])
        self.assertIn("auth", payload)
        self.assertTrue(payload["auth"]["session_token"])
        self.assertTrue(payload["config"]["app"]["auth_configured"])
        self.assertNotIn("secret", payload["config"]["app"])

    def test_recovery_reset_returns_new_recovery_code(self):
        saved_state = {"config": self._base_config(secret="old-secret")}
        saved_state["config"]["app"]["recovery_code"] = "ABCD-EFGH-IJKL-MNOP"

        def fake_load_config():
            return copy.deepcopy(saved_state["config"])

        def fake_save_config(config):
            saved_state["config"] = copy.deepcopy(config)

        with patch.object(web, "load_config", side_effect=fake_load_config), patch.object(
            web, "save_config", side_effect=fake_save_config
        ):
            response = self.client.post(
                "/api/auth/recover",
                json={
                    "recovery_code": "ABCD-EFGH-IJKL-MNOP",
                    "secret": "brand-new-secret",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["recovery_code"])
        self.assertEqual(payload["secret"], "brand-new-secret")
        self.assertIn("auth", payload)
        self.assertTrue(payload["auth"]["session_token"])
        self.assertEqual(saved_state["config"]["app"]["secret"], "brand-new-secret")
        self.assertNotEqual(saved_state["config"]["app"]["recovery_code"], "ABCD-EFGH-IJKL-MNOP")

    def test_recovery_email_sends_current_recovery_code_without_auth_prompt(self):
        saved_config = self._base_config()
        saved_config["app"]["recovery_code"] = "ABCD-EFGH-IJKL-MNOP"
        saved_config["notifications"] = {
            "enabled": False,
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "transport_mode": "ssl",
            "sender_email": "sender@example.com",
            "sender_name": "Auto PT",
            "smtp_username": "sender@example.com",
            "smtp_password": "saved-password",
            "recipient_email": "receiver@example.com",
        }

        with patch.object(web, "load_config", return_value=copy.deepcopy(saved_config)), patch.object(
            web, "send_email_notification", return_value=(True, "邮件已发送")
        ) as mock_send:
            response = self.client.post("/api/auth/recovery-email")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertIn("邮箱", payload["message"])
        self.assertTrue(mock_send.called)
        sent_settings = mock_send.call_args.args[0]
        self.assertEqual(sent_settings["recipient_email"], "receiver@example.com")
        self.assertEqual(sent_settings["smtp_password"], "saved-password")

    def test_recovery_email_requires_mail_config(self):
        saved_config = self._base_config()
        saved_config["app"]["recovery_code"] = "ABCD-EFGH-IJKL-MNOP"
        saved_config["notifications"] = {
            "enabled": False,
            "smtp_host": "",
            "smtp_port": 0,
            "transport_mode": "ssl",
            "sender_email": "",
            "sender_name": "",
            "smtp_username": "",
            "smtp_password": "",
            "recipient_email": "",
        }

        with patch.object(web, "load_config", return_value=copy.deepcopy(saved_config)), patch.object(
            web, "send_email_notification"
        ) as mock_send:
            response = self.client.post("/api/auth/recovery-email")

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["success"])
        self.assertIn("没有设置邮箱信息", payload["error"])
        mock_send.assert_not_called()

    def test_recovery_code_auto_send_ignores_notification_toggle(self):
        saved_config = self._base_config()
        saved_config["notifications"] = {
            "enabled": False,
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "transport_mode": "ssl",
            "sender_email": "sender@example.com",
            "sender_name": "Auto PT",
            "smtp_username": "sender@example.com",
            "smtp_password": "saved-password",
            "recipient_email": "receiver@example.com",
        }
        saved_state = {"config": copy.deepcopy(saved_config)}

        def fake_load_config():
            return copy.deepcopy(saved_state["config"])

        def fake_save_config(config):
            saved_state["config"] = copy.deepcopy(config)

        with patch.object(web, "load_config", side_effect=fake_load_config), patch.object(
            web, "save_config", side_effect=fake_save_config
        ), patch.object(web, "send_email_notification", return_value=(True, "邮件已发送")) as mock_send:
            response = self.client.post(
                "/api/config",
                json={"app": {"secret": "brand-new-secret"}},
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["recovery_code"])
        self.assertTrue(payload["recovery_code_sent"])
        self.assertTrue(mock_send.called)
        sent_settings = mock_send.call_args.args[0]
        self.assertFalse(sent_settings["enabled"])
        self.assertEqual(sent_settings["recipient_email"], "receiver@example.com")

    def test_notification_test_uses_saved_password_without_exposing_it(self):
        saved_config = self._base_config()
        saved_config["notifications"] = {
            "enabled": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "transport_mode": "ssl",
            "sender_email": "sender@example.com",
            "sender_name": "Auto PT",
            "smtp_username": "sender@example.com",
            "smtp_password": "saved-password",
            "recipient_email": "receiver@example.com",
        }

        with patch.object(web, "load_config", return_value=copy.deepcopy(saved_config)), patch.object(
            web, "send_email_notification", return_value=(True, "邮件已发送")
        ) as mock_send:
            response = self.client.post(
                "/api/notifications/test",
                json={
                    "notifications": {
                        "enabled": True,
                        "smtp_host": "smtp.example.com",
                        "smtp_port": 465,
                        "transport_mode": "ssl",
                        "sender_email": "sender@example.com",
                        "sender_name": "Auto PT",
                        "recipient_email": "receiver@example.com",
                    },
                    "subject": "Auto PT 邮件通知测试",
                    "message": "测试邮件",
                },
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertNotIn("smtp_password", payload)
        self.assertTrue(mock_send.called)
        sent_settings = mock_send.call_args.args[0]
        self.assertEqual(sent_settings["smtp_password"], "saved-password")
        self.assertEqual(sent_settings["recipient_email"], "receiver@example.com")

    def test_preview_returns_friendly_error_for_missing_rss_url(self):
        fake_config = FakeConfig(
            [
                {
                    "name": "demo",
                    "type": "mteam",
                    "base_url": "https://example.com",
                    "rss_url": "",
                    "enabled": True,
                    "schedule": {"interval": 300},
                    "download_settings": {"auto_download": False},
                }
            ]
        )

        with patch("src.config.Config", return_value=fake_config):
            response = self.client.post(
                "/api/preview",
                json={"site_name": "demo"},
                headers={"Authorization": "Bearer test-secret"},
            )

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["success"])
        self.assertIn("未配置 RSS 地址", payload["message"])

    @patch("src.history.DownloadHistory")
    def test_get_history_includes_site_and_size_metadata(self, mock_history_cls):
        mock_history_cls.return_value.get_all.return_value = {
            "184998": {
                "title": "Example Torrent",
                "hash": "abc123",
                "site_name": "hdtime",
                "category": "影剧/综艺/HD",
                "size": 14.75,
                "status": "completed",
                "added_at": "2026-03-19T10:47:23.234449",
                "completed_time": "2026-03-19T10:50:00.000000",
                "progress_history": [{"progress": 1.0, "time": "2026-03-19T10:50:00.000000"}],
            }
        }

        response = self.client.get(
            "/api/history",
            headers={"Authorization": "Bearer test-secret"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(len(payload["records"]), 1)

        record = payload["records"][0]
        self.assertEqual(record["site_name"], "hdtime")
        self.assertEqual(record["category"], "影剧/综艺/HD")
        self.assertEqual(record["size"], 14.75)
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["completed_time"], "2026-03-19T10:50:00.000000")

    def test_download_history_update_progress_uses_ratio_completion(self):
        with tempfile.TemporaryDirectory(prefix="auto_pt_history_") as temp_dir:
            history_file = Path(temp_dir) / "history.json"
            history = DownloadHistory(str(history_file))
            history.add(
                "184998",
                title="Example Torrent",
                torrent_hash="abc123",
                site_name="hdtime",
                category="剧集",
                size=14.75,
            )

            history.update_progress("184998", 100)

            record = history.get_record("184998")
            self.assertEqual(record["status"], "completed")
            self.assertIsNotNone(record["completed_time"])
            self.assertEqual(record["progress_history"][-1]["progress"], 1.0)

    def test_download_history_completion_statistics_counts_completed_records(self):
        with tempfile.TemporaryDirectory(prefix="auto_pt_history_") as temp_dir:
            history_file = Path(temp_dir) / "history.json"
            history = DownloadHistory(str(history_file))
            history._history = {
                "184998": {
                    "title": "Today Complete",
                    "status": "completed",
                    "added_at": "2026-03-19T10:47:23.234449",
                    "completed_time": "2026-03-20T08:00:00",
                    "progress_history": [{"progress": 1.0, "time": "2026-03-20T08:00:00"}],
                },
                "185021": {
                    "title": "Hidden Complete",
                    "status": "completed",
                    "hidden": True,
                    "added_at": "2026-03-15T10:47:23.234449",
                    "completed_time": "2026-03-15T12:00:00",
                    "progress_history": [{"progress": 1.0, "time": "2026-03-15T12:00:00"}],
                },
                "185099": {
                    "title": "Downloading",
                    "status": "downloading",
                    "added_at": "2026-03-20T09:00:00",
                    "completed_time": None,
                    "progress_history": [{"progress": 0.5, "time": "2026-03-20T09:00:00"}],
                },
            }

            stats = history.get_completion_statistics(now=datetime(2026, 3, 20, 12, 0, 0))

        self.assertEqual(stats["today_completed"], 1)
        self.assertEqual(stats["week_completed"], 2)
        self.assertEqual(stats["total_completed"], 2)
        self.assertEqual(stats["total_records"], 3)

    def test_download_history_mark_deleted_keeps_completed_statistics(self):
        with tempfile.TemporaryDirectory(prefix="auto_pt_history_") as temp_dir:
            history_file = Path(temp_dir) / "history.json"
            history = DownloadHistory(str(history_file))
            history.add(
                "184998",
                title="Completed Torrent",
                torrent_hash="torrent-hash-123",
                site_name="hdtime",
                category="剧集",
                size=14.75,
            )
            history.update_progress("184998", 100)
            history.add(
                "185099",
                title="Downloading Torrent",
                torrent_hash="torrent-hash-456",
                site_name="hdtime",
                category="剧集",
                size=9.25,
            )

            self.assertTrue(
                history.mark_deleted(
                    "184998",
                    source="auto_cleanup",
                    reason="auto_cleanup_completed",
                    delete_files=True,
                )
            )
            self.assertTrue(
                history.mark_deleted(
                    "185099",
                    source="qb_sync",
                    reason="manual_removed_during_download",
                )
            )

            record_completed = history.get_record("184998")
            record_downloading = history.get_record("185099")
            stats = history.get_completion_statistics(now=datetime(2026, 3, 20, 12, 0, 0))

        self.assertEqual(record_completed["status"], "deleted")
        self.assertEqual(record_completed["deleted_source"], "auto_cleanup")
        self.assertEqual(record_completed["deleted_reason"], "auto_cleanup_completed")
        self.assertEqual(record_completed["deleted_from_status"], "completed")
        self.assertTrue(record_completed["deleted_files"])
        self.assertTrue(record_completed["deleted_at"])
        self.assertEqual(record_downloading["status"], "deleted")
        self.assertEqual(record_downloading["deleted_source"], "qb_sync")
        self.assertEqual(record_downloading["deleted_reason"], "manual_removed_during_download")
        self.assertEqual(record_downloading["deleted_from_status"], "downloading")
        self.assertTrue(record_downloading["deleted_at"])
        self.assertEqual(stats["total_completed"], 1)
        self.assertEqual(stats["total_deleted"], 2)

    @patch("src.history.DownloadHistory")
    @patch("src.qbittorrent.QBittorrentClient")
    @patch("src.config.Config")
    def test_get_stats_uses_completion_statistics(self, mock_config_cls, mock_qb_cls, mock_history_cls):
        mock_config = Mock()
        mock_config.get.side_effect = lambda key, default=None: {
            "schedule": {"enabled": True, "interval": 300, "cleanup_interval": 1800}
        }.get(key, default)
        mock_config.qbittorrent = {
            "host": "http://127.0.0.1:8080",
            "username": "admin",
            "password": "secret",
        }
        mock_config.pt_sites = []
        mock_config.get_enabled_sites.return_value = []
        mock_config_cls.return_value = mock_config

        mock_history = Mock()
        mock_history.get_completion_statistics.return_value = {
            "today_completed": 2,
            "week_completed": 5,
            "total_completed": 10,
            "total_records": 12,
        }
        mock_history.count.return_value = 12
        mock_history_cls.return_value = mock_history

        mock_qb = Mock()
        mock_qb.get_version.return_value = "v5.0"
        mock_qb.get_torrents.return_value = [
            {"hash": "a", "progress": 0.5, "state": "downloading"},
            {"hash": "b", "progress": 1.0, "state": "uploading"},
            {"hash": "c", "progress": 1.0, "state": "pausedUP"},
        ]
        mock_qb_cls.return_value = mock_qb

        response = self.client.get(
            "/api/stats",
            headers={"Authorization": "Bearer test-secret"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["history_stats"]["today_completed"], 2)
        self.assertEqual(payload["history_stats"]["week_completed"], 5)
        self.assertEqual(payload["history_stats"]["total_completed"], 10)
        self.assertEqual(payload["history_count"], 12)
        self.assertEqual(payload["history_completed_count"], 10)
        self.assertEqual(payload["download_trend"]["today"], 2)
        self.assertEqual(payload["download_trend"]["total"], 10)
        self.assertEqual(payload["qb_stats"]["downloading"], 1)
        self.assertEqual(payload["qb_stats"]["completed"], 1)
        self.assertEqual(payload["qb_stats"]["seeding"], 1)
        self.assertEqual(payload["qb_stats"]["paused"], 0)
        self.assertEqual(payload["qb_stats"]["total"], 3)

    @patch("src.history.DownloadHistory")
    def test_get_history_include_hidden_returns_hidden_records(self, mock_history_cls):
        mock_history_cls.return_value.get_all.return_value = {
            "184998": {
                "title": "Hidden Torrent",
                "hash": "abc123",
                "site_name": "hdtime",
                "category": "剧集",
                "size": 14.75,
                "status": "completed",
                "hidden": True,
                "added_at": "2026-03-19T10:47:23.234449",
                "completed_time": None,
                "progress_history": [],
            }
        }

        response = self.client.get(
            "/api/history?include_hidden=1",
            headers={"Authorization": "Bearer test-secret"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(len(payload["records"]), 1)
        self.assertTrue(payload["records"][0]["hidden"])

    @patch("src.history.DownloadHistory")
    def test_get_history_includes_deleted_metadata(self, mock_history_cls):
        mock_history_cls.return_value.get_all.return_value = {
            "184998": {
                "title": "Deleted Torrent",
                "hash": "abc123",
                "site_name": "hdtime",
                "category": "剧集",
                "size": 14.75,
                "status": "deleted",
                "deleted_at": "2026-03-20T09:00:00",
                "deleted_reason": "manual_removed_during_download",
                "deleted_source": "qb_sync",
                "deleted_from_status": "downloading",
                "deleted_files": False,
                "added_at": "2026-03-19T10:47:23.234449",
                "completed_time": None,
                "progress_history": [{"progress": 0.5, "time": "2026-03-20T08:00:00"}],
            }
        }

        response = self.client.get(
            "/api/history?include_hidden=1",
            headers={"Authorization": "Bearer test-secret"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        record = payload["records"][0]
        self.assertEqual(record["status"], "deleted")
        self.assertEqual(record["deleted_reason"], "manual_removed_during_download")
        self.assertEqual(record["deleted_source"], "qb_sync")
        self.assertEqual(record["deleted_from_status"], "downloading")
        self.assertFalse(record["deleted_files"])

    @patch("src.history.DownloadHistory")
    def test_restore_history_batch_can_restore_selected_ids(self, mock_history_cls):
        history = Mock()
        history._history = {
            "184998": {"title": "Hidden A", "hidden": True},
            "185021": {"title": "Hidden B", "hidden": True},
            "185099": {"title": "Visible C"},
        }
        history._save = Mock()
        mock_history_cls.return_value = history

        response = self.client.post(
            "/api/history/restore",
            json={"ids": ["184998"]},
            headers={"Authorization": "Bearer test-secret"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["restored"], 1)
        self.assertNotIn("hidden", history._history["184998"])
        self.assertTrue(history._history["185021"]["hidden"])
        history._save.assert_called_once()

    def test_get_config_includes_dual_notification_flags(self):
        saved_config = self._base_config()
        saved_config["notifications"] = {
            "enabled": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "transport_mode": "ssl",
            "sender_email": "sender@example.com",
            "sender_name": "Auto PT",
            "smtp_username": "sender@example.com",
            "smtp_password": "saved-password",
            "recipient_email": "receiver@example.com",
        }

        safe_config = web.filter_sensitive_config(saved_config)
        notifications = safe_config["notifications"]

        self.assertTrue(notifications["enabled"])
        self.assertTrue(notifications["download_start_enabled"])
        self.assertTrue(notifications["download_complete_enabled"])

    def test_config_promotes_legacy_qb_url_when_host_is_empty(self):
        with tempfile.TemporaryDirectory(prefix="auto_pt_config_") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "qbittorrent:\n"
                "  host: ''\n"
                "  url: 127.0.0.1:8080\n"
                "  username: admin\n"
                "  password: secret\n",
                encoding="utf-8",
            )

            config = Config(str(config_path))

        self.assertEqual(config.qbittorrent.get("host"), "127.0.0.1:8080")


class QBittorrentClientRegressionTests(unittest.TestCase):
    def setUp(self):
        qb_module._LOGIN_FAILURE_STATE.clear()

    def tearDown(self):
        qb_module._LOGIN_FAILURE_STATE.clear()

    def test_bare_host_is_normalized_and_api_url_is_absolute(self):
        client = QBittorrentClient(host="127.0.0.1:8585", username="admin", password="secret")
        self.assertEqual(client.host, "http://127.0.0.1:8585")

        client._authenticated = True
        client.session = Mock()
        response = Mock()
        response.status_code = 200
        response.text = "Ok."
        response.raise_for_status = Mock()
        client.session.post.return_value = response

        with patch.object(client, "_calculate_info_hash", return_value="torrent-hash-123"):
            success, torrent_hash = client.add_torrent(
                torrent_data=b"fake-torrent-data",
                torrent_title="Demo Torrent",
            )

        self.assertTrue(success)
        self.assertEqual(torrent_hash, "torrent-hash-123")
        self.assertEqual(
            client.session.post.call_args.args[0],
            "http://127.0.0.1:8585/api/v2/torrents/add",
        )

    def test_login_failure_uses_shared_cooldown_without_repeating_request(self):
        client1 = QBittorrentClient(host="127.0.0.1:8585", username="admin", password="secret")
        response = Mock()
        response.status_code = 403
        response.text = "Forbidden"
        response.raise_for_status = Mock()
        client1.session = Mock()
        client1.session.post.return_value = response

        with patch.object(qb_module.logger, "warning") as mock_warning, patch.object(
            qb_module.logger, "error"
        ) as mock_error:
            self.assertFalse(client1.login())
            self.assertEqual(client1.session.post.call_count, 1)

            client2 = QBittorrentClient(host="127.0.0.1:8585", username="admin", password="secret")
            client2.session = Mock()
            self.assertFalse(client2.login())
            client2.session.post.assert_not_called()

        self.assertTrue(mock_warning.called)
        mock_error.assert_not_called()


class NotificationRegressionTests(unittest.TestCase):
    def test_qb_state_to_status_maps_uploading_to_seeding(self):
        self.assertEqual(qb_state_to_status(1.0, "uploading")["state"], "seeding")
        self.assertEqual(qb_state_to_status(1.0, "stalledUP")["state"], "seeding")
        self.assertEqual(qb_state_to_status(1.0, "pausedUP")["state"], "completed")

    def test_process_single_site_sends_download_start_notification_when_enabled(self):
        site_client = Mock()
        site_client.fetch_torrents.return_value = [
            AttrDict(
                {
                    "torrent_id": "184998",
                    "title": "Example Torrent",
                    "size": 14.75,
                    "site_name": "hdtime",
                    "category": "剧集",
                }
            )
        ]
        site_client.download_torrent.return_value = b"fake-torrent-data"

        qb = Mock()
        qb.add_torrent.return_value = (True, "torrent-hash-123")
        qb.get_torrents.return_value = [{"hash": "torrent-hash-123", "progress": 0.1}]

        history = Mock()
        history.contains.return_value = False

        notification_settings = {
            "enabled": True,
            "download_start_enabled": True,
            "download_complete_enabled": False,
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "transport_mode": "ssl",
            "sender_email": "sender@example.com",
            "sender_name": "Auto PT",
            "smtp_username": "sender@example.com",
            "smtp_password": "saved-password",
            "recipient_email": "receiver@example.com",
        }

        with patch.object(runner, "create_site_client", return_value=site_client), patch.object(
            runner, "send_email_notification", return_value=(True, "邮件已发送")
        ) as mock_send:
            filtered_count, new_count = runner.process_single_site(
                site={
                    "name": "hdtime",
                    "type": "mteam",
                    "base_url": "https://hdtime.org",
                    "rss_url": "https://hdtime.org/torrentrss.php?passkey=abc",
                    "enabled": True,
                    "filter": {},
                    "download_settings": {"auto_download": True},
                    "tags": ["hdtime"],
                },
                qb=qb,
                qb_config={"save_path": "/downloads", "category": "", "pause_added": False},
                history=history,
                notification_settings=notification_settings,
            )

        self.assertEqual(filtered_count, 1)
        self.assertEqual(new_count, 1)
        self.assertTrue(mock_send.called)
        self.assertEqual(history.add.call_count, 1)
        history.mark_notification_sent.assert_called_once_with("184998", "download_start")
        subject = mock_send.call_args.kwargs["subject"]
        self.assertIn("下载开始", subject)

    def test_sync_download_completion_notifications_sends_once(self):
        with tempfile.TemporaryDirectory(prefix="auto_pt_history_") as temp_dir:
            history_file = Path(temp_dir) / "history.json"
            history = DownloadHistory(str(history_file))
            history.add(
                "184998",
                title="Completed Torrent",
                torrent_hash="torrent-hash-123",
                site_name="hdtime",
                category="剧集",
                size=14.75,
            )

            qb = Mock()
            qb.get_torrents.return_value = [
                {
                    "hash": "torrent-hash-123",
                    "progress": 1.0,
                    "name": "Completed Torrent",
                    "category": "剧集",
                    "size": 14.75,
                }
            ]

            config = Mock()
            config.notifications = {
                "enabled": True,
                "download_start_enabled": False,
                "download_complete_enabled": True,
                "smtp_host": "smtp.example.com",
                "smtp_port": 465,
                "transport_mode": "ssl",
                "sender_email": "sender@example.com",
                "sender_name": "Auto PT",
                "smtp_username": "sender@example.com",
                "smtp_password": "saved-password",
                "recipient_email": "receiver@example.com",
            }
            config.qbittorrent = {"host": "http://127.0.0.1:8080", "username": "admin", "password": "secret"}

            with patch.object(runner, "QBittorrentClient", return_value=qb), patch.object(
                runner, "DownloadHistory", return_value=history
            ), patch.object(runner, "send_email_notification", return_value=(True, "邮件已发送")) as mock_send:
                first_count = runner.sync_download_completion_notifications(config)
                second_count = runner.sync_download_completion_notifications(config)

            self.assertEqual(first_count, 1)
            self.assertEqual(second_count, 0)
            self.assertEqual(mock_send.call_count, 1)
            record = history.get_record("184998")
            self.assertTrue(record["download_complete_notified_at"])

    def test_sync_download_completion_notifications_marks_seeding_without_mail_toggle(self):
        with tempfile.TemporaryDirectory(prefix="auto_pt_history_") as temp_dir:
            history_file = Path(temp_dir) / "history.json"
            history = DownloadHistory(str(history_file))
            history.add(
                "184998",
                title="Completed Torrent",
                torrent_hash="torrent-hash-123",
                site_name="hdtime",
                category="剧集",
                size=14.75,
            )

            qb = Mock()
            qb.get_torrents.return_value = [
                {
                    "hash": "torrent-hash-123",
                    "progress": 1.0,
                    "state": "uploading",
                    "name": "Completed Torrent",
                    "category": "剧集",
                    "size": 14.75,
                }
            ]

            config = Mock()
            config.notifications = {
                "enabled": False,
                "download_start_enabled": False,
                "download_complete_enabled": False,
                "smtp_host": "",
                "smtp_port": 0,
                "transport_mode": "ssl",
                "sender_email": "",
                "sender_name": "",
                "smtp_username": "",
                "smtp_password": "",
                "recipient_email": "",
            }
            config.qbittorrent = {"host": "http://127.0.0.1:8080", "username": "admin", "password": "secret"}

            with patch.object(runner, "QBittorrentClient", return_value=qb), patch.object(
                runner, "DownloadHistory", return_value=history
            ), patch.object(runner, "send_email_notification") as mock_send:
                notified_count = runner.sync_download_completion_notifications(config)

            record = history.get_record("184998")
            self.assertEqual(notified_count, 0)
            self.assertEqual(record["status"], "seeding")
            self.assertTrue(record["completed_time"])
            mock_send.assert_not_called()

    def test_send_email_notification_falls_back_from_ssl_to_starttls(self):
        settings = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "transport_mode": "ssl",
            "sender_email": "sender@example.com",
            "sender_name": "Auto PT",
            "smtp_username": "sender@example.com",
            "smtp_password": "saved-password",
            "recipient_email": "receiver@example.com",
        }

        ssl_client = MagicMock()
        ssl_client.__enter__.side_effect = smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

        starttls_client = MagicMock()
        starttls_client.__enter__.return_value = starttls_client
        starttls_client.ehlo.return_value = (250, b"OK")
        starttls_client.starttls.return_value = (220, b"Ready")
        starttls_client.login.return_value = (235, b"Authentication successful")
        starttls_client.send_message.return_value = {}

        with patch.object(notifications.smtplib, "SMTP_SSL", return_value=ssl_client) as mock_ssl, patch.object(
            notifications.smtplib, "SMTP", return_value=starttls_client
        ) as mock_smtp:
            success, message = notifications.send_email_notification(
                settings,
                subject="Auto PT 邮件通知测试",
                text="测试邮件",
            )

        self.assertTrue(success)
        self.assertEqual(message, "邮件已发送")
        mock_ssl.assert_called_once()
        mock_smtp.assert_called_once()
        starttls_client.starttls.assert_called_once()
        starttls_client.send_message.assert_called_once()

    def test_send_email_notification_reports_auth_failure_without_fallback(self):
        settings = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "transport_mode": "ssl",
            "sender_email": "sender@example.com",
            "sender_name": "Auto PT",
            "smtp_username": "sender@example.com",
            "smtp_password": "saved-password",
            "recipient_email": "receiver@example.com",
        }

        ssl_client = MagicMock()
        ssl_client.__enter__.return_value = ssl_client
        ssl_client.ehlo.return_value = (250, b"OK")
        ssl_client.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication failed")

        with patch.object(notifications.smtplib, "SMTP_SSL", return_value=ssl_client) as mock_ssl, patch.object(
            notifications.smtplib, "SMTP"
        ) as mock_smtp:
            success, message = notifications.send_email_notification(
                settings,
                subject="Auto PT 邮件通知测试",
                text="测试邮件",
            )

        self.assertFalse(success)
        self.assertIn("SMTP 登录失败", message)
        mock_ssl.assert_called_once()
        mock_smtp.assert_not_called()

    @patch("src.runner.DownloadHistory")
    @patch("src.runner.QBittorrentClient")
    @patch("src.runner.Config")
    def test_cleanup_completed_marks_deleted_records(self, mock_config_cls, mock_qb_cls, mock_history_cls):
        mock_config = Mock()
        mock_config.get_enabled_sites.return_value = [
            {
                "name": "hdtime",
                "download_settings": {"auto_delete": True, "delete_files": True},
                "schedule": {"interval": 300, "cleanup_interval": 0},
                "tags": ["hdtime"],
            }
        ]
        mock_config.qbittorrent = {
            "host": "http://127.0.0.1:8080",
            "username": "admin",
            "password": "secret",
        }
        mock_config_cls.return_value = mock_config

        history = Mock()
        history.find_torrent_ids_by_hash.return_value = ["184998"]
        history.mark_deleted.return_value = True
        mock_history_cls.return_value = history

        qb = Mock()
        qb.get_completed_torrents.return_value = [{"hash": "torrent-hash-123", "name": "Completed Torrent"}]
        qb.delete_torrent.return_value = True
        mock_qb_cls.return_value = qb

        deleted_count = runner.cleanup_completed(mock_config)

        self.assertEqual(deleted_count, 1)
        qb.delete_torrent.assert_called_once_with("torrent-hash-123", delete_files=True)
        history.find_torrent_ids_by_hash.assert_called_once_with("torrent-hash-123")
        history.mark_deleted.assert_called_once_with(
            "184998",
            source="auto_cleanup",
            reason="auto_cleanup_completed",
            delete_files=True,
        )

    @patch("src.runner.DownloadHistory")
    @patch("src.runner.QBittorrentClient")
    @patch("src.runner.Config")
    def test_sync_deleted_history_records_marks_missing_torrents(self, mock_config_cls, mock_qb_cls, mock_history_cls):
        mock_config = Mock()
        mock_config.qbittorrent = {
            "host": "http://127.0.0.1:8080",
            "username": "admin",
            "password": "secret",
        }
        mock_config_cls.return_value = mock_config

        history = Mock()
        history.get_all.return_value = {
            "184998": {
                "title": "Completed Torrent",
                "hash": "torrent-hash-123",
                "status": "completed",
                "completed_time": "2026-03-20T08:00:00",
                "progress_history": [{"progress": 1.0, "time": "2026-03-20T08:00:00"}],
            },
            "185099": {
                "title": "Downloading Torrent",
                "hash": "torrent-hash-456",
                "status": "downloading",
                "completed_time": None,
                "progress_history": [{"progress": 0.5, "time": "2026-03-20T09:00:00"}],
            },
        }
        history.mark_deleted.side_effect = [True, True]
        mock_history_cls.return_value = history

        qb = Mock()
        qb.get_torrents.return_value = [{"hash": "torrent-hash-789", "name": "Keep Torrent"}]
        mock_qb_cls.return_value = qb

        deleted_count = runner.sync_deleted_history_records(mock_config)

        self.assertEqual(deleted_count, 2)
        qb.get_torrents.assert_called_once_with(raise_on_error=True)
        self.assertEqual(history.mark_deleted.call_count, 2)
        self.assertEqual(
            history.mark_deleted.call_args_list[0].args,
            ("184998",),
        )
        self.assertEqual(history.mark_deleted.call_args_list[0].kwargs["reason"], "manual_removed_after_complete")
        self.assertEqual(history.mark_deleted.call_args_list[1].kwargs["reason"], "manual_removed_during_download")

    @patch("src.runner.DownloadHistory")
    @patch("src.runner.QBittorrentClient")
    @patch("src.runner.Config")
    def test_sync_deleted_history_records_skips_when_qb_unreachable(self, mock_config_cls, mock_qb_cls, mock_history_cls):
        mock_config = Mock()
        mock_config.qbittorrent = {
            "host": "http://127.0.0.1:8080",
            "username": "admin",
            "password": "secret",
        }
        mock_config_cls.return_value = mock_config

        history = Mock()
        history.get_all.return_value = {
            "184998": {
                "title": "Completed Torrent",
                "hash": "torrent-hash-123",
                "status": "completed",
                "completed_time": "2026-03-20T08:00:00",
                "progress_history": [{"progress": 1.0, "time": "2026-03-20T08:00:00"}],
            }
        }
        mock_history_cls.return_value = history

        qb = Mock()
        qb.get_torrents.side_effect = RuntimeError("qB unavailable")
        mock_qb_cls.return_value = qb

        deleted_count = runner.sync_deleted_history_records(mock_config)

        self.assertEqual(deleted_count, 0)
        history.mark_deleted.assert_not_called()


class MTeamClientRegressionTests(unittest.TestCase):
    def _build_mock_config(self):
        mock_config = Mock()
        mock_config.get.side_effect = lambda key, default=None: default
        return mock_config

    def _build_entry(self, **kwargs):
        entry = AttrDict(kwargs)
        if "tags" in kwargs:
            entry["tags"] = [
                AttrDict(tag) if not isinstance(tag, AttrDict) else tag
                for tag in kwargs["tags"]
            ]
        if "enclosures" in kwargs:
            entry["enclosures"] = [
                AttrDict(item) if not isinstance(item, AttrDict) else item
                for item in kwargs["enclosures"]
            ]
        return entry

    @patch("src.mteam.Config")
    def test_fetch_torrents_skips_network_for_empty_rss_url(self, mock_config_cls):
        mock_config_cls.return_value = self._build_mock_config()

        client = MTeamClient(base_url="https://example.com", rss_url="", site_name="demo")
        client.session = Mock()

        torrents = client.fetch_torrents()

        self.assertEqual(torrents, [])
        client.session.get.assert_not_called()

    @patch("src.mteam.feedparser.parse")
    @patch("src.mteam.Config")
    def test_fetch_torrents_extracts_category_from_category_field_when_tags_missing(
        self, mock_config_cls, mock_feed_parse
    ):
        mock_config_cls.return_value = self._build_mock_config()
        mock_feed_parse.return_value = AttrDict(
            {
                "entries": [
                    self._build_entry(
                        title="Example Drama",
                        link="https://example.com/details.php?id=123",
                        category="剧集",
                        enclosures=[],
                        published="Thu, 19 Mar 2026 12:00:00 +0800",
                    )
                ],
                "bozo": False,
            }
        )

        client = MTeamClient(base_url="https://example.com", rss_url="https://example.com/rss", site_name="demo")
        mock_response = Mock()
        mock_response.content = b"<rss />"
        mock_response.raise_for_status.return_value = None
        client.session = Mock()
        client.session.get.return_value = mock_response

        torrents = client.fetch_torrents()

        self.assertEqual(len(torrents), 1)
        self.assertEqual(torrents[0].category, "剧集")
        self.assertEqual(torrents[0].torrent_id, "123")

    @patch("src.mteam.feedparser.parse")
    @patch("src.mteam.Config")
    def test_fetch_torrents_prefers_real_category_tag_over_status_tag(
        self, mock_config_cls, mock_feed_parse
    ):
        mock_config_cls.return_value = self._build_mock_config()
        mock_feed_parse.return_value = AttrDict(
            {
                "entries": [
                    self._build_entry(
                        title="Example Series",
                        link="https://example.com/details.php?id=456",
                        category="TV Series/HD",
                        tags=[
                            {"term": "free", "scheme": "https://example.com/promo/free"},
                            {"term": "TV Series/HD", "scheme": "https://example.com/torrents.php?cat=402"},
                        ],
                        enclosures=[],
                        published="Thu, 19 Mar 2026 12:05:00 +0800",
                    )
                ],
                "bozo": False,
            }
        )

        client = MTeamClient(base_url="https://example.com", rss_url="https://example.com/rss", site_name="demo")
        mock_response = Mock()
        mock_response.content = b"<rss />"
        mock_response.raise_for_status.return_value = None
        client.session = Mock()
        client.session.get.return_value = mock_response

        torrents = client.fetch_torrents()

        self.assertEqual(len(torrents), 1)
        self.assertEqual(torrents[0].category, "影劇/綜藝/HD")

    @patch("src.mteam.feedparser.parse")
    @patch("src.mteam.Config")
    def test_fetch_torrents_falls_back_to_site_category_id_mapping(self, mock_config_cls, mock_feed_parse):
        mock_config_cls.return_value = self._build_mock_config()
        mock_feed_parse.return_value = AttrDict(
            {
                "entries": [
                    self._build_entry(
                        title="Example Hdtime Drama",
                        link="https://hdtime.org/details.php?id=789",
                        tags=[
                            {"term": "", "scheme": "https://hdtime.org/torrents.php?cat=402"},
                        ],
                        enclosures=[],
                        published="Thu, 19 Mar 2026 12:10:00 +0800",
                    )
                ],
                "bozo": False,
            }
        )

        client = MTeamClient(base_url="https://hdtime.org", rss_url="https://hdtime.org/rss", site_name="hdtime")
        mock_response = Mock()
        mock_response.content = b"<rss />"
        mock_response.raise_for_status.return_value = None
        client.session = Mock()
        client.session.get.return_value = mock_response

        torrents = client.fetch_torrents()

        self.assertEqual(len(torrents), 1)
        self.assertEqual(torrents[0].category, "剧集")

    @patch("src.mteam.feedparser.parse")
    @patch("src.mteam.Config")
    def test_fetch_torrents_skips_notice_items_without_torrent_id(self, mock_config_cls, mock_feed_parse):
        mock_config_cls.return_value = self._build_mock_config()
        mock_feed_parse.return_value = AttrDict(
            {
                "entries": [
                    self._build_entry(
                        title="RSS获取成功：频率限制提醒",
                        link="https://www.pttime.org/getrss.php",
                        enclosures=[],
                        published="Thu, 19 Mar 2026 12:42:40 +0800",
                    )
                ],
                "bozo": False,
            }
        )

        client = MTeamClient(base_url="https://www.pttime.org", rss_url="https://www.pttime.org/torrentrss.php", site_name="ptt")
        mock_response = Mock()
        mock_response.content = b"<rss />"
        mock_response.raise_for_status.return_value = None
        client.session = Mock()
        client.session.get.return_value = mock_response

        torrents = client.fetch_torrents()

        self.assertEqual(torrents, [])


if __name__ == "__main__":
    unittest.main()
