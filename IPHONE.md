# Make reels from your iPhone

Tap a shortcut, wait for GitHub to wake up, then paste an Instagram link or upload a video, add your caption, generate, and download. Your PC can stay off.

## One-time setup

1. Open [Create a GitHub token](https://github.com/settings/personal-access-tokens/new?name=Reel%20Generator%20iPhone&target_name=Xinthian&expires_in=90&codespaces_lifecycle_admin=write) while signed in as **Xinthian**.
2. Under **Repository access**, select **Only select repositories**, then **instagram-reel-generator**. Check that **Codespaces lifecycle admin** has **Read and write** access, then generate the token.
3. Copy the token directly into the shortcut's Authorization header below. Keep it out of chat and do not share the completed shortcut. The token expires after **90 days**; generate a replacement and update that header when it expires.
4. On your iPhone, open **Shortcuts**, tap **+**, and name it **Reel Generator**. Add these five actions in order.

### 1. URL

```text
https://api.github.com/user/codespaces/reel-generator-j65vxr9g7wx25wp9/start
```

### 2. Get Contents of URL

Use the URL from action 1. Expand the action and set **Method** to **POST**. Leave **Request Body** as an empty **JSON** body. Add these headers:

| Key | Value |
| --- | --- |
| Authorization | `Bearer YOUR_TOKEN` — replace `YOUR_TOKEN` with your copied token, keeping the space after `Bearer` |
| Accept | `application/vnd.github+json` |
| X-GitHub-Api-Version | `2026-03-10` |

### 3. Wait

Set **30 seconds**.

### 4. URL

```text
https://xinthian.github.io/reel/
```

### 5. Open URLs

Use the URL from action 4. Save the shortcut; optionally choose **Add to Home Screen** from its menu.

## Each time you make a reel

Tap **Reel Generator** and allow access to GitHub if Shortcuts asks. Startup sometimes takes longer than 30 seconds; wait a little and refresh the webpage if it is not ready.

Sign in to GitHub in Safari if prompted. The app opens directly without an app username or password.

For an Instagram link, leave the caption blank to generate an AI headline. For an uploaded video, enter a caption or select a screenshot and tap **EXECUTE_OCR** to generate one. AI uses free models only. Generate and download the reel before closing the page. The Codespace is configured to stop after **10 minutes of inactivity**; closing the page does not stop it immediately.

With **no payment method saved**, GitHub blocks further use when your free allowance is exhausted instead of charging you. No billing setup is needed now. Storage also uses the allowance while the Codespace is stopped. If you add a payment method later, review your Codespaces spending limit first.

Sources: [Apple's API actions](https://support.apple.com/guide/shortcuts/apd58d46713f/ios), [GitHub's start API](https://docs.github.com/en/rest/codespaces/codespaces#start-a-codespace-for-the-authenticated-user), [GitHub's billing rules](https://docs.github.com/en/billing/concepts/product-billing/github-codespaces).
