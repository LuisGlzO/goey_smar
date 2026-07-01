from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from monitor.amazon_creators import CreatorProductContent
from monitor.models import MonitorRun, Product, ProductCheck
from monitor.telegram import send_product_alert


class ProductTelegramAlertTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(asin="B0G3CY83L5", name="Nombre local", max_price=Decimal("1000"))
        self.run = MonitorRun.objects.create()
        self.check = ProductCheck.objects.create(
            run=self.run,
            product=self.product,
            availability=ProductCheck.Availability.AVAILABLE,
            price=Decimal("900"),
            product_url="https://www.amazon.com.mx/dp/B0G3CY83L5",
        )

    @override_settings(
        TELEGRAM_BOT_TOKEN="product-token",
        TELEGRAM_CHAT_ID="-100123",
        AMAZON_ASSOCIATE_TAG="goeygeeks2023-20",
    )
    @patch("monitor.telegram.safe_get_product_content")
    @patch("monitor.telegram.requests.get")
    @patch("monitor.telegram.requests.post")
    def test_product_alert_uses_creator_image_title_and_detail_url(self, post, get, safe_get_product_content):
        safe_get_product_content.return_value = CreatorProductContent(
            title="Pokemon TCG: Mega Evolution Ascended Heroes Elite Trainer Box",
            image_url="https://m.media-amazon.com/images/I/product.jpg",
            detail_page_url="https://www.amazon.com.mx/dp/B0G3CY83L5?tag=goeygeeks2023-20&linkCode=ogi",
        )
        get.return_value.raw = Mock()
        post.return_value.json.return_value = {"result": {"message_id": 88}}

        message_id = send_product_alert(self.product, self.check)

        self.assertEqual(message_id, "88")
        get.assert_called_once_with("https://m.media-amazon.com/images/I/product.jpg", stream=True, timeout=30)
        post.assert_called_once()
        self.assertIn("/sendPhoto", post.call_args.args[0])
        self.assertIn("botproduct-token", post.call_args.args[0])
        payload = post.call_args.kwargs["data"]
        self.assertEqual(payload["chat_id"], "-100123")
        self.assertIn("Pokemon TCG: Mega Evolution Ascended Heroes Elite Trainer Box", payload["caption"])
        self.assertIn("tag=goeygeeks2023-20&amp;linkCode=ogi", payload["caption"])
        self.assertEqual(post.call_args.kwargs["files"], {"photo": get.return_value.raw})

    @override_settings(
        TELEGRAM_BOT_TOKEN="product-token",
        TELEGRAM_CHAT_ID="-100123",
        AMAZON_ASSOCIATE_TAG="goeygeeks2023-20",
    )
    @patch("monitor.telegram.safe_get_product_content")
    @patch("monitor.telegram.requests.get")
    @patch("monitor.telegram.requests.post")
    def test_product_manual_affiliate_url_overrides_creator_detail_url(self, post, get, safe_get_product_content):
        self.product.affiliate_url = "https://amzn.to/manual"
        self.product.save(update_fields=("affiliate_url",))
        safe_get_product_content.return_value = CreatorProductContent(
            title="Nombre desde API",
            image_url="https://m.media-amazon.com/images/I/product.jpg",
            detail_page_url="https://www.amazon.com.mx/dp/B0G3CY83L5?tag=goeygeeks2023-20&linkCode=ogi",
        )
        get.return_value.raw = Mock()
        post.return_value.json.return_value = {"result": {"message_id": 90}}

        send_product_alert(self.product, self.check)

        payload = post.call_args.kwargs["data"]
        self.assertIn("https://amzn.to/manual", payload["caption"])
        self.assertNotIn("linkCode=ogi", payload["caption"])

    @override_settings(
        TELEGRAM_BOT_TOKEN="product-token",
        TELEGRAM_CHAT_ID="-100123",
        AMAZON_ASSOCIATE_TAG="goeygeeks2023-20",
        AMAZON_CREATORS_API_PARTNER_TAG="goeygeeks2023-20",
    )
    @patch("monitor.telegram.safe_get_product_content", return_value=None)
    @patch("monitor.telegram.requests.post")
    def test_product_alert_falls_back_to_text_message_without_creator_content(self, post, safe_get_product_content):
        post.return_value.json.return_value = {"result": {"message_id": 89}}

        message_id = send_product_alert(self.product, self.check)

        self.assertEqual(message_id, "89")
        self.assertIn("/sendMessage", post.call_args.args[0])
        self.assertIn("botproduct-token", post.call_args.args[0])
        payload = post.call_args.kwargs["json"]
        self.assertIn("Nombre local", payload["text"])
        self.assertIn(
            "https://www.amazon.com.mx/dp/B0G3CY83L5?tag=goeygeeks2023-20&amp;linkCode=ogi&amp;th=1&amp;psc=1",
            payload["text"],
        )
