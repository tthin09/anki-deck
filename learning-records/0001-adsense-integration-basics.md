# 0001 — AdSense integration basics

- **Mission link:** Monetize the existing Vocabulary Deck Generator.
- **Key insight:** adding the publisher script is only technical integration; it does not grant approval or guarantee ads/revenue. Submit and verify the live site in AdSense, then wait for review.
- **Current app:** `web/index.html` is the shared HTML shell. The global AdSense script belongs in its `<head>` after Google supplies the real account-specific publisher ID. Do not paste a placeholder or invent an ad unit.
- **Next:** after approval, enable Auto ads or create an ad unit; publish a privacy policy and check geographic consent requirements. Make sure the app has sufficient useful public content, not just an authenticated utility screen.
- **Risk to resolve:** public access to deck generation can create Gemini API costs and abuse; set usage limits/monitoring before launch.
