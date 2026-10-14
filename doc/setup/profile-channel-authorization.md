# Authorizing separate YouTube channels, Facebook Pages and Instagram accounts

This owner setup guide records the lessons from configuring InPulso World and
InPulso Football. It does not change the publishing requirements. Canonical
configuration and account isolation are defined in
[18-configuration.md](../specifications/18-configuration.md).

## Safety and account isolation

- Keep credentials in the ignored root `.env` or ignored `secrets/` directory.
  Never paste tokens, app secrets or OAuth callback URLs into chat or commits.
- An OAuth client identifies an application; a token authorizes an account or
  channel. Sharing the application does not mean sharing its channel tokens.
- Set Football's Content Profile credential prefix (`env_prefix`) to
  `FOOTBALL`. A profile without a prefix uses global publishing credentials.
- The prefix applies to every publishing platform, not just YouTube or
  Facebook. Configure all enabled Football platforms with scoped credentials,
  or disable the unconfigured platforms. Scoped accounts do not fall back to
  World's credentials.
- Existing Runs retain their profile snapshots. Confirm the account prefix on
  a new Run rather than assuming a profile edit fixes an older Run.
- Start with `publishing.mode=dry_run`. Read-only credential checks prove
  identity and access, not a successful media upload.

## YouTube: same Google account, separate channels

### The two kinds of JSON

| File | Purpose |
| --- | --- |
| `secrets/youtube_oauth.json` | Google OAuth client configuration; can be shared by World and Football |
| `secrets/youtube_token.json` | Authorization for the World channel |
| `secrets/football_youtube_token.json` | Separate authorization for the Football channel |

The channel token JSON is created by authorization, not downloaded from Google
Cloud Console. The publisher uploads to the channel authorized by that token;
setting a different channel ID is not a substitute for channel authorization.

### Configure paths

Keep World's existing configuration and add:

```dotenv
YOUTUBE_CLIENT_SECRETS_FILE=secrets/youtube_oauth.json
FOOTBALL_YOUTUBE_CLIENT_SECRETS_FILE=secrets/youtube_oauth.json
FOOTBALL_YOUTUBE_TOKEN_FILE=secrets/football_youtube_token.json
```

World's legacy token is discovered beside its client file as
`youtube_token.json`; the global publisher does not currently support an
explicit `YOUTUBE_TOKEN_FILE` setting.

The credential helper defaults to the repository's `secrets/` directory for
scoped YouTube authorization: shared `youtube_oauth.json` and
`<prefix>_youtube_token.json`. Explicit environment paths override those
defaults. The runtime publisher has different fallback paths under
`DATA_DIR/secrets/`, so the explicit Football entries above keep authorization
and publishing aligned. No additional directory under the database is needed.

### Authorize Football

1. Stop the ClipFactory application normally, leaving PostgreSQL and Dragonfly
   running. The OAuth callback helper needs port 8000.
2. Ensure the OAuth client permits this exact redirect URI:
   `http://localhost:8000/auth/youtube/callback`.
3. From the repository root, run:

   ```bash
   uv run --project backend python scripts/check_credentials.py \
     --profile football \
     --youtube-auth
   ```

4. Open the printed authorization URL if the browser does not open.
5. Sign in using the Google account that owns the channels, and select
   **InPulso Football** when Google offers the channel/account chooser.
6. Grant the requested upload and read permissions.
7. Let the local callback complete. If it does not load, paste the complete
   redirected URL into the waiting terminal only.
8. Confirm the helper reports the Football channel, not World. It saves the
   token JSON at the configured Football path.
9. Restart from the repository root:

   ```bash
   uv run --project backend clipfactory run
   ```

The helper creates missing token destination directories. If saving failed
after exchanging the authorization code, rerun authorization: the exchanged
code cannot be reused.

### Troubleshooting

| Symptom | Check or action |
| --- | --- |
| Token saved for World | Repeat consent and select Football; never copy World's token to Football's file |
| Football absent from chooser | Confirm Football appears in YouTube's Switch account menu for the signed-in Google account |
| Callback cannot bind port 8000 | Stop ClipFactory before running authorization |
| Old database destination still used | Correct `FOOTBALL_YOUTUBE_TOKEN_FILE` in `.env`; check for a process environment override |
| Client file not found | Check `FOOTBALL_YOUTUBE_CLIENT_SECRETS_FILE`; relative paths resolve from the repository root in the helper |
| No refresh token returned | Review Google's consent result before retrying; do not blindly revoke the shared app because World may also be affected |

## Facebook: User authorization, then a Page token

### Understand the identities

| Item | Meaning |
| --- | --- |
| Meta app ID | Identifies the ClipFactory developer application |
| Facebook User token | Authorizes the person who manages the Page |
| Facebook Page ID | Numeric identity of the Football Page, not the person or app |
| Facebook Page token | Used by ClipFactory to publish to that specific Page |

Football must be a Facebook **Page**, not an additional personal profile.
World and Football may share the Meta app, but use separate Page tokens.

### Obtain a User token with access to Football

1. Open [Graph API Explorer](https://developers.facebook.com/tools/explorer/).
2. Select your ClipFactory app in **Meta App**.
3. In the separate **User or Page** selector, choose **Get User Access Token**,
   not an App token or another Page's token.
4. Request `pages_show_list`, `pages_read_engagement` and
   `pages_manage_posts` for Page discovery/read/publishing. Additional
   permissions or app review may be required for the intended operation;
   follow Meta's current documentation and grant only what is needed.
5. Sign in as the person managing Football. During consent, grant the app
   access to Football.
6. If the app is in development mode, ensure a different managing account has
   the appropriate accepted app role.
7. Verify the current token with a **GET** request:

   ```text
   me?fields=id,name
   ```

   It should identify the managing person. If it says `ClipFactory`, inspect
   the token type in the debugger: it could identify a Page or the app rather
   than the intended person. Selecting ClipFactory as the app is correct;
   using an App token for Page discovery is not.

### Find the Page ID

With the User token, run:

```text
me/accounts?fields=id,name,tasks
```

Find Football and record its `id` as `FOOTBALL_FACEBOOK_PAGE_ID`. The relevant
tasks must permit content creation, such as `CREATE_CONTENT`.

`me?fields=id,name,tasks` is not the Pages listing endpoint.

### When `/me/accounts` returns an empty list

Having the right permission names does not prove the app has access to any
selected Page.

1. Switch into Football on Facebook and open
   **Settings > Page setup > Page access** (labels may vary).
2. Confirm the intended person has Facebook access and the necessary content
   permissions; check for pending invitations. Business Suite task access
   alone is not the same as direct Facebook access.
3. Switch back to the person's Facebook account.
4. Open **Settings > Business integrations > ClipFactory > View and edit**.
5. Ensure **InPulso Football** is among the Pages granted to the integration.
6. Generate a fresh User token after changing the grant and retry
   `/me/accounts`.
7. Use [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/)
   privately to check validity, User token type, intended app, scopes and,
   where shown, granular Page grants.

In the observed setup, the person already had full Page access, but Football
also needed to be added to the app's Business integrations authorization.
Do not remove the entire integration as a first troubleshooting step: doing
so may invalidate World's working credentials.

### Obtain a long-lived Page token

Retrieving a Page token from a short-lived User token does not automatically
make the Page token long-lived.

1. Debug the **User token** in Meta's Access Token Debugger.
2. Use **Extend Access Token**, if offered, and copy the resulting long-lived
   User token. A long-lived User token normally lasts around 60 days.
3. If the debugger cannot extend it, use Meta's documented server-side exchange
   with the app ID and app secret. Never expose the app secret in chat or
   client-side code. An expired or invalidated User token must be reauthorized,
   not extended.
4. Replace Graph API Explorer's token with that long-lived User token.
5. Run this **GET** request, substituting the actual Page ID:

   ```text
   YOUR_FOOTBALL_PAGE_ID?fields=id,name,access_token
   ```

   Alternatively, use:

   ```text
   me/accounts?fields=id,name,access_token,tasks
   ```

6. Confirm the returned `id` and `name` identify Football. Copy that Page's
   `access_token`, not the User token.
7. Debug the new Page token privately to confirm validity, Page identity and
   expiration. A Page token derived from a long-lived User token can have no
   scheduled expiration, but security changes, revoked grants or lost Page
   access can still invalidate it.
8. Save locally:

   ```dotenv
   FOOTBALL_FACEBOOK_PAGE_ID=your_football_page_id
   FOOTBALL_FACEBOOK_ACCESS_TOKEN=your_football_page_token
   ```

`FACEBOOK_LONG_LIVED_TOKEN` is an optional local intermediate credential used
for token derivation; it is not the publisher's Page token setting. Keep
World's `FACEBOOK_ACCESS_TOKEN` and `FACEBOOK_PAGE_ID` unchanged.

### Common Facebook failures

| Symptom | Meaning or action |
| --- | --- |
| Error 190: session invalidated | Obtain fresh User authorization; the old token cannot derive a Page token |
| User identity is correct, Pages list is empty | Check Page access and the app's selected Page grants |
| `/me` returns Football with a Page token | Its returned ID identifies that Page; do not use this token to enumerate the person's Pages |
| Token identifies another Page | Retrieve the entry matching Football's Page ID |
| Page token appears temporary | Derive it again using an extended User token and check it in the debugger |
| Identity check succeeds but publication fails | Check operation permissions, app access/review, media requirements and the actual provider error |

## Instagram: API Setup and account invitation

ClipFactory uses **Instagram API with Instagram Login** and an Instagram
professional account's token. A Facebook Page token is not interchangeable
with this Instagram token.

### Connect the new account

The owner used the app's Instagram Business **API Setup** page, with this URL
shape (replace the placeholders with your own IDs):

```text
https://developers.facebook.com/apps/YOUR_APP_ID/instagram-business/API-Setup/?business_id=YOUR_BUSINESS_ID
```

1. Open your Meta app's **Instagram > API Setup** page.
2. Add/select the new Instagram professional account, such as
   **InPulso Football**, rather than the existing World account.
3. Follow **Generate token** and the account authorization prompts.
4. Sign into the new Instagram account itself and accept the app invitation.
   In the observed setup, this was a separate step after token generation.
   Check the account's app/tester invitations or notifications; menu labels
   can vary. Accept the invitation from Football, not World.
5. Return to API Setup and confirm the account is connected. If generation or
   authorization is blocked by a pending invitation, retry after accepting it.
6. Save the account's Instagram token and numeric Instagram user ID locally:

   ```dotenv
   FOOTBALL_INSTAGRAM_ACCESS_TOKEN=your_football_instagram_token
   FOOTBALL_INSTAGRAM_USER_ID=your_football_instagram_user_id
   ```

Keep World's `INSTAGRAM_ACCESS_TOKEN` and `INSTAGRAM_USER_ID` unchanged.
The user ID here is the Instagram account ID, not the Meta app ID, Business
ID or Facebook Page ID.

### Confirm identity and token lifetime

The credential helper checks Instagram's `/me` endpoint for `user_id` and
`username`, and compares the returned identity with the configured scoped
user ID. Use the verification command below to confirm it identifies Football.

Do not assume an API Setup token never expires. Follow the token lifetime,
exchange and refresh instructions for **Instagram Login**, rather than the
Facebook Page token procedure above. Token generation and invitation acceptance
were reported by the owner; a successful Instagram upload and the new token's
lifetime have not been independently verified.

| Symptom | Check or action |
| --- | --- |
| Invitation remains pending | Sign into the invited Instagram account and accept the app invitation there |
| Authorization blocked before acceptance | Complete the invitation step, then retry API Setup authorization |
| Identity check returns World | Generate a token for Football; do not reuse World's token |
| User ID mismatch | Use the Instagram user ID returned for the authorized account, not a Page or Business ID |
| Token expired or invalid | Follow Instagram Login's renewal instructions; do not use a Facebook Page token |

## Verify locally without publishing

From the repository root:

```bash
uv run --project backend python scripts/check_credentials.py --profile football
```

Expected identity checks:

```text
[ OK ] YouTube: channel 'InPulso Football' (...)
[ OK ] Instagram: @your_football_username (user ...)
[ OK ] Facebook: Page 'InPulso Football' (...)
```

The command checks all three scoped platforms independently, so a failure for
one may appear alongside successful identity checks for the others.

Before enabling live publishing, confirm Football's profile prefix is
`FOOTBALL`, World's configuration is unchanged, all enabled platforms have
the intended scoped accounts, and a new Run uses the expected profile.
Token presence or successful identity lookup alone is not proof of a
successful upload.

## Official references

- [YouTube OAuth authorization](https://developers.google.com/youtube/v3/guides/authentication)
- [YouTube server-side OAuth](https://developers.google.com/youtube/v3/guides/auth/server-side-web-apps)
- [Meta Pages API getting started](https://developers.facebook.com/docs/pages-api/getting-started/)
- [Meta long-lived User and Page tokens](https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived/)
- [Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/)
