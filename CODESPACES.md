# Codespaces runbook

The app runs on GitHub Codespaces. Once configured, you can wake it and make reels entirely from your phone browser; your local computer can stay off. The forwarded port is **private**: sign in to GitHub as the codespace owner. The app opens directly without an additional login.

- Existing repository: `Xinthian/instagram-reel-generator`
- Existing display name: `reel-generator`
- Existing codespace name: `reel-generator-j65vxr9g7wx25wp9`
- Wake URL: <https://reel-generator-j65vxr9g7wx25wp9.github.dev>
- Short app URL: <https://xinthian.github.io/reel/>
- App URL: <https://reel-generator-j65vxr9g7wx25wp9-7008.app.github.dev>

Keep the existing codespace unless you intend to update the URL in your phone automation. The repository changes do not change the live codespace until you pull them and rebuild its dev container.

## Free-only usage setup

The user confirmed that no payment method is saved on the GitHub account. GitHub blocks Codespaces when the included allowance is exhausted without a valid payment method, so no budget setup or upgrade is needed for this workflow. When the allowance runs out, wait for its monthly reset. Storage uses the allowance even while stopped. AI captions are restricted to free OpenRouter models with zero provider-price caps. See [Codespaces billing](https://docs.github.com/en/billing/concepts/product-billing/github-codespaces).

If a payment method is added later, first create an account-wide **Product-level → Codespaces** budget of **$0** with **Stop usage when budget limit is reached** enabled in [GitHub billing](https://github.com/settings/billing). That covers both compute and storage; an idle timeout is not a spending limit. See [GitHub's budget instructions](https://docs.github.com/en/billing/how-tos/set-up-budgets).

## Daily use from your phone

For the intended twice-daily workflow, set up the [iPhone shortcut](IPHONE.md) once. Tap it to wake the Codespace and open the app, make and download your reel, then close Safari. No local computer is needed. The manual browser fallback is:

1. Open the [wake URL](https://reel-generator-j65vxr9g7wx25wp9.github.dev) and sign in to GitHub as the codespace owner. If prompted, select **Start** and wait for the codespace to open. You can also select the existing `reel-generator` at [github.com/codespaces](https://github.com/codespaces).
2. Open the [reel generator](https://xinthian.github.io/reel/). Sign in to GitHub if prompted. If the server is still starting, wait a few seconds and reload.
3. Paste an Instagram URL and leave the caption blank for an AI headline, or upload a video and enter a caption or generate one from a screenshot. Generate and download the result. Prefer Upload if Instagram blocks downloads from the cloud IP.
4. When finished, use the codespace's **… → Stop codespace** menu at [github.com/codespaces](https://github.com/codespaces), or let its idle timeout stop it. Bookmark both URLs for next time.

No local server, GitHub CLI, or phone Shortcut is needed for these steps. The optional wake helpers below automate starting the same codespace. See [GitHub's browser start/stop instructions](https://docs.github.com/en/codespaces/developing-in-a-codespace/stopping-and-starting-a-codespace).

Finish within the configured idle window; this instance was created with a **10-minute** timeout. An open app tab and health requests do **not** guarantee that the codespace stays awake. Server output goes to a log file, so phone-only use can time out even while a render is running. If the session expires, wake it again and resubmit the job. Other editor or terminal activity can extend the idle window; closing the app tab does not start a separate sleep timer. These rules follow [GitHub's inactivity definition](https://docs.github.com/en/codespaces/setting-your-user-preferences/setting-your-timeout-period-for-github-codespaces#inactivity-defined).

## One-time configuration

Create these Codespaces secrets and grant this repository access:

| Secret | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | Optional for manual captions; required for automatic headlines and screenshot captions |
| `COOKIES_TXT` | Optional Netscape-format Instagram cookies; written to a private runtime file on startup |

Use newly rotated credentials if the old ones appeared in source/history. Stop and restart the codespace after updating secrets. Do not paste credentials into this document, source files, or shared Shortcut exports.

The dev container enables AI with `AI_CAPTIONS_ENABLED=true` and `OPENROUTER_MODEL=openrouter/free`. Configure a fresh provider key before deploying this change; the historical exposed key must be replaced and revoked. Paid model IDs are rejected, and zero provider-price caps prevent paid fallback. Free-model limits or outages return an error; manual captions remain available. Set `AI_CAPTIONS_ENABLED=false` and rebuild to disable AI.

Review the actual existing codespace's `idle_timeout_minutes` with:

```bash
gh api /user/codespaces/reel-generator-j65vxr9g7wx25wp9 --jq .idle_timeout_minutes
```

The historical instance was created with a 10-minute idle timeout; plan phone-only sessions within that window unless you have verified a different value. GitHub's personal default idle-timeout setting applies to **new** codespaces. A 30-minute default is a practical choice when intentionally creating a replacement, but a replacement changes the app URL and requires updating your Shortcut. Do not recreate the current instance just to wake it. Check organization limits and actual billing/storage usage. See [GitHub's timeout settings](https://docs.github.com/en/codespaces/setting-your-user-preferences/setting-your-timeout-period-for-github-codespaces).

## Optional laptop wake helper

```bash
gh auth refresh -h github.com -s codespace
bash scripts/wake-codespace.sh
```

The helper selects the unique `reel-generator` display name in the repository. Set `CODESPACE_NAME` explicitly if multiple instances match. It starts a stopped instance, polls `GET /user/codespaces/{name}`, explicitly makes port 7008 private, and checks the server through `gh codespace ssh`. Readiness requires HTTP 200 and JSON `ok: true`; HTML login pages, redirects, malformed JSON, and false health responses fail the check.

It waits up to five minutes, then exits with a useful error. It does not create codespaces, change idle settings, or upgrade packages. To stop after use:

```bash
gh codespace stop -c reel-generator-j65vxr9g7wx25wp9
```

## iPhone Shortcut

[IPHONE.md](IPHONE.md) contains the five actions and exact URLs. It uses one repository-scoped token to start the Codespace, waits 30 seconds, and opens Safari. Startup can take longer; refresh if needed. Browser login is separate from the shortcut's token. The laptop helper remains available for diagnostic readiness checks.

## Startup and troubleshooting

`.devcontainer/start.sh` optionally writes cookie secrets with mode 600, and starts the server detached. Dependencies install at image build time and remain pinned during wake. Logs are stored inside the codespace at `/tmp/reel-generator-<uid>/server.log`; check `id -u` for the UID. Port 7008 is forwarded privately by default. The laptop helper also restores private visibility explicitly.

A local readiness check inside the codespace is:

```bash
curl --fail http://127.0.0.1:7008/api/health
```

A successful response is `{"ok":true}`. A 429 processing response means another job is using the worker. Rebuild the dev container after dependency or Dockerfile changes; restarting alone does not install the new versions.

Keep port 7008 private: application routes no longer require app credentials. The laptop wake helper always selects Private. See [GitHub’s port security rules](https://docs.github.com/en/codespaces/reference/security-in-github-codespaces#port-forwarding).
