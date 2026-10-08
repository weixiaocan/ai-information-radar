from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

from src.hosting.environment import EnvironmentValidationError, validate_hosted_environment
from src.hosting.secrets import SecretMaterializationError, materialize_secret_file


class HostedEnvironmentTest(unittest.TestCase):
    def test_state_profile_reports_only_missing_variable_names(self) -> None:
        secret_value = "do-not-print-this-value"
        environment = {
            "AI_RADAR_STATE_HOST": "state.example.com",
            "AI_RADAR_STATE_USER": "ai-radar-sync",
            "AI_RADAR_STATE_ROOT": "/srv/ai-radar-data",
            "AI_RADAR_STATE_SSH_KEY_PATH": secret_value,
        }

        with self.assertRaises(EnvironmentValidationError) as captured:
            validate_hosted_environment(environment, profile="state")

        message = str(captured.exception)
        self.assertIn("AI_RADAR_KNOWN_HOSTS_PATH", message)
        self.assertNotIn(secret_value, message)

    def test_state_profile_accepts_safe_locator_values(self) -> None:
        environment = {
            "AI_RADAR_STATE_HOST": "129.211.15.170",
            "AI_RADAR_STATE_USER": "ai-radar-sync",
            "AI_RADAR_STATE_ROOT": "/srv/ai-radar-data",
            "AI_RADAR_STATE_SSH_KEY_PATH": "/tmp/id_ed25519",
            "AI_RADAR_KNOWN_HOSTS_PATH": "/tmp/known_hosts",
        }

        validate_hosted_environment(environment, profile="state")

    def test_unsafe_remote_root_is_rejected_without_echoing_value(self) -> None:
        unsafe_value = "/srv/data; echo leaked"
        environment = {
            "AI_RADAR_STATE_HOST": "129.211.15.170",
            "AI_RADAR_STATE_USER": "ai-radar-sync",
            "AI_RADAR_STATE_ROOT": unsafe_value,
            "AI_RADAR_STATE_SSH_KEY_PATH": "/tmp/id_ed25519",
            "AI_RADAR_KNOWN_HOSTS_PATH": "/tmp/known_hosts",
        }

        with self.assertRaises(EnvironmentValidationError) as captured:
            validate_hosted_environment(environment, profile="state")

        self.assertIn("AI_RADAR_STATE_ROOT", str(captured.exception))
        self.assertNotIn(unsafe_value, str(captured.exception))

    def test_production_profile_requires_delivery_and_provider_secrets(self) -> None:
        with self.assertRaises(EnvironmentValidationError) as captured:
            validate_hosted_environment({}, profile="production")

        message = str(captured.exception)
        for variable in (
            "YOUTUBE_API_KEY",
            "DEEPSEEK_API_KEY",
            "SUPADATA_API_KEY",
            "FEISHU_WEBHOOK_URL",
            "GMAIL_CREDENTIALS_PATH",
            "GMAIL_TOKEN_PATH",
        ):
            self.assertIn(variable, message)

    def test_materialize_secret_file_decodes_without_logging_content(self) -> None:
        payload = b'{"refresh_token":"private-value"}'
        encoded = base64.b64encode(payload).decode("ascii")
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "gmail-token.json"
            materialize_secret_file(encoded, destination, label="GMAIL_TOKEN_JSON_B64")
            self.assertEqual(payload, destination.read_bytes())

    def test_invalid_secret_payload_error_does_not_echo_value(self) -> None:
        invalid_value = "not-valid-base64!"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "gmail-token.json"
            with self.assertRaises(SecretMaterializationError) as captured:
                materialize_secret_file(invalid_value, destination, label="GMAIL_TOKEN_JSON_B64")

        self.assertIn("GMAIL_TOKEN_JSON_B64", str(captured.exception))
        self.assertNotIn(invalid_value, str(captured.exception))


if __name__ == "__main__":
    unittest.main()
