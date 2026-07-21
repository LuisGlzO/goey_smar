from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from monitor import amazon_creators
from monitor.amazon_creators import get_product_content


class AmazonCreatorsApiTests(SimpleTestCase):
    def setUp(self):
        amazon_creators._token_cache["access_token"] = ""
        amazon_creators._token_cache["expires_at"] = 0.0

    @override_settings(
        AMAZON_CREATORS_API_CLIENT_ID="client",
        AMAZON_CREATORS_API_CLIENT_SECRET="secret",
        AMAZON_CREATORS_API_CREDENTIAL_VERSION="3",
        AMAZON_CREATORS_API_MARKETPLACE="www.amazon.com.mx",
        AMAZON_CREATORS_API_PARTNER_TAG="goeygeeks2023-20",
        AMAZON_CREATORS_API_LANGUAGES=["es_MX"],
        AMAZON_CREATORS_API_BASE_URL="https://creatorsapi.amazon",
        AMAZON_CREATORS_API_TOKEN_URL="https://api.amazon.com/auth/o2/token",
        AMAZON_CREATORS_API_TIMEOUT_SECONDS=15,
    )
    @patch("monitor.amazon_creators.requests.post")
    def test_get_product_content_fetches_title_image_and_detail_url(self, post):
        token_response = Mock()
        token_response.json.return_value = {"access_token": "access-token", "expires_in": 3600}

        item_response = Mock()
        item_response.json.return_value = {
            "itemsResult": {
                "items": [
                    {
                        "asin": "B0G3CY83L5",
                        "detailPageURL": "https://www.amazon.com.mx/dp/B0G3CY83L5?tag=goeygeeks2023-20",
                        "images": {"primary": {"large": {"url": "https://m.media-amazon.com/image.jpg"}}},
                        "itemInfo": {"title": {"displayValue": "Pokemon TCG Elite Trainer Box"}},
                    }
                ]
            }
        }
        post.side_effect = [token_response, item_response]

        content = get_product_content("B0G3CY83L5")

        self.assertEqual(content.title, "Pokemon TCG Elite Trainer Box")
        self.assertEqual(content.image_url, "https://m.media-amazon.com/image.jpg")
        self.assertEqual(content.detail_page_url, "https://www.amazon.com.mx/dp/B0G3CY83L5?tag=goeygeeks2023-20")
        post.assert_any_call(
            "https://api.amazon.com/auth/o2/token",
            json={
                "grant_type": "client_credentials",
                "client_id": "client",
                "client_secret": "secret",
                "scope": "creatorsapi::default",
            },
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        post.assert_any_call(
            "https://creatorsapi.amazon/catalog/v1/getItems",
            json={
                "itemIds": ["B0G3CY83L5"],
                "itemIdType": "ASIN",
                "marketplace": "www.amazon.com.mx",
                "partnerTag": "goeygeeks2023-20",
                "resources": [
                    "images.primary.large", "itemInfo.title",
                    "offersV2.listings.availability", "offersV2.listings.price",
                ],
                "languagesOfPreference": ["es_MX"],
            },
            headers={
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
                "x-marketplace": "www.amazon.com.mx",
            },
            timeout=15,
        )

    @override_settings(
        AMAZON_CREATORS_API_CLIENT_ID="client",
        AMAZON_CREATORS_API_CLIENT_SECRET="secret",
        AMAZON_CREATORS_API_CREDENTIAL_VERSION="2.1",
        AMAZON_CREATORS_API_MARKETPLACE="www.amazon.com.mx",
        AMAZON_CREATORS_API_PARTNER_TAG="goeygeeks2023-20",
        AMAZON_CREATORS_API_LANGUAGES=[],
        AMAZON_CREATORS_API_BASE_URL="https://creatorsapi.amazon",
        AMAZON_CREATORS_API_TOKEN_URL="https://creatorsapi.auth.us-west-2.amazoncognito.com/oauth2/token",
        AMAZON_CREATORS_API_TIMEOUT_SECONDS=15,
    )
    @patch("monitor.amazon_creators.requests.post")
    def test_v2_credentials_include_version_in_authorization_header(self, post):
        token_response = Mock()
        token_response.json.return_value = {"access_token": "access-token", "expires_in": 3600}
        item_response = Mock()
        item_response.json.return_value = {"itemsResult": {"items": []}}
        post.side_effect = [token_response, item_response]

        get_product_content("B0G3CY83L5")

        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer access-token, Version 2.1")
