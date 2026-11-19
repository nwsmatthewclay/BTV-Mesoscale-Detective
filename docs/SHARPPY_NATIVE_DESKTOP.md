# Native SHARPpy / NSHARP browser desktop

This deployment runs the upstream SHARPpy Qt application inside the existing Cloudflare Container. It is not a browser recreation of NSHARP.

## Runtime layout

- `sharppy` starts the official SHARPpy desktop application.
- Xvfb supplies a virtual 1680x1050 display.
- Openbox provides a lightweight window manager.
- x11vnc exposes that display only on container loopback.
- noVNC/websockify serves the HTML5 desktop viewer on container port 6080.
- The existing FastAPI SHARPpy service remains on port 8000.
- The Worker forwards `/desktop/*` to port 6080 and proxies the noVNC WebSocket through `/websockify`.

## Required Cloudflare setup

Do not expose the desktop WebSocket without its access token.

1. Add these three repository Actions secrets: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, and a long random `SHARPPY_DESKTOP_TOKEN`. The deploy workflow installs the desktop token as a Worker secret after deployment. Then run `.github/workflows/deploy-sharppy-api.yml` from the Actions tab, or deploy locally with:

   ```sh
   npx wrangler deploy --config wrangler.sharppy.toml
   ```

2. If deploying locally, generate a long random token and set it as a Cloudflare Worker secret:

   ```sh
   npx wrangler secret put SHARPPY_DESKTOP_TOKEN --config wrangler.sharppy.toml
   ```

   Enter the token at the prompt. Do not commit it to Git or put it in `wrangler.sharppy.toml`.

3. Set `service_url` in `mesoscale/sharppy_api_config.json` to the HTTPS origin printed by Wrangler, for example `https://btv-sharppy-api.<your-workers-subdomain>.workers.dev`. Commit that configuration update so the Pages workbench can find the service.

4. Open `nsharp.html`, enter the same Worker origin and token, and select **Launch native NSHARP**.

The static noVNC client is not itself protected, but the actual desktop WebSocket requires the secret. The VNC server listens only on loopback inside the container and is not directly exposed.

## Smoke tests

The native SHARPpy validation workflow checks Python diagnostics, JavaScript syntax, shell syntax, and builds the desktop container. The GUI smoke test launches the upstream app under Xvfb and expects it to remain running until timeout; it does not replace a deployed end-to-end browser test.

## Operational caveats

This is a shared, single-instance desktop session. Concurrent forecasters will see and control the same SHARPpy window. It is suitable for an initial alpha test, not a multi-user production deployment. A production rollout should use one isolated desktop/container per authenticated user or workstation, add Cloudflare Access, and validate container sizing and idle lifecycle behavior.
