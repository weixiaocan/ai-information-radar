import unittest
from unittest.mock import Mock, patch

from src.output.feishu_delivery import FeishuDelivery


class FeishuDeliveryTest(unittest.TestCase):
    @patch("src.output.feishu_delivery.time.sleep")
    @patch("src.output.feishu_delivery.requests.post")
    def test_send_retries_on_frequency_limit(self, mock_post: Mock, mock_sleep: Mock) -> None:
        first_response = Mock()
        first_response.raise_for_status.return_value = None
        first_response.json.return_value = {"code": 11232, "msg": "frequency limited"}

        second_response = Mock()
        second_response.raise_for_status.return_value = None
        second_response.json.return_value = {"code": 0, "msg": "success"}

        mock_post.side_effect = [first_response, second_response]

        delivery = FeishuDelivery(
            webhook_url="https://example.com/webhook",
            timeout_seconds=10,
            max_retries=3,
            retry_backoff_seconds=(1, 2, 3),
        )
        payload = {"msg_type": "interactive"}

        result = delivery.send(payload)

        self.assertEqual(result["code"], 0)
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    @patch("src.output.feishu_delivery.time.sleep")
    @patch("src.output.feishu_delivery.requests.post")
    def test_send_raises_after_exhausting_frequency_limit_retries(self, mock_post: Mock, mock_sleep: Mock) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"code": 11232, "msg": "frequency limited"}
        mock_post.return_value = response

        delivery = FeishuDelivery(
            webhook_url="https://example.com/webhook",
            timeout_seconds=10,
            max_retries=2,
            retry_backoff_seconds=(1, 2),
        )

        with self.assertRaises(RuntimeError):
            delivery.send({"msg_type": "interactive"})

        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
