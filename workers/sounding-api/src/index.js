import { Container, getContainer, switchPort } from "@cloudflare/containers";

export class SharpPyContainer extends Container {
  defaultPort = 8000;
  requiredPorts = [8000, 6080];
  sleepAfter = "20m";
  enableInternet = true;

  envVars = {
    BUFKIT_CACHE_DIR: "/tmp/bufkit-cache",
    BUFKIT_CACHE_TTL_SECONDS: "300",
  };

  onStart() {
    console.log("BTV SHARPpy API and native NSHARP desktop started");
  }

  onError(error) {
    console.error("BTV SHARPpy container error:", error);
    throw error;
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/__worker_health") {
      return Response.json({
        status: "ok",
        service: "BTV SHARPpy API + native NSHARP desktop",
        desktop_transport: "WebSocket/noVNC",
      });
    }

    // The native desktop's VNC stream is only reachable through this
    // authenticated WebSocket route. Store SHARPPY_DESKTOP_TOKEN as a
    // Cloudflare Worker secret; never put it in wrangler vars or source.
    if (url.pathname === "/websockify") {
      const expected = env.SHARPPY_DESKTOP_TOKEN;
      const supplied = url.searchParams.get("token");
      if (!expected || !supplied || supplied !== expected) {
        return new Response("Native NSHARP desktop access is not authorized.", {
          status: 403,
          headers: { "content-type": "text/plain; charset=utf-8" },
        });
      }
      const upstream = new URL(request.url);
      upstream.search = "";
      return getContainer(env.SHARPPY_API).fetch(
        switchPort(new Request(upstream, request), 6080),
      );
    }

    // Serve noVNC's static client from the second container port. Strip the
    // public /desktop prefix so /desktop/vnc.html maps to /vnc.html upstream.
    if (url.pathname === "/desktop" || url.pathname.startsWith("/desktop/")) {
      const upstream = new URL(request.url);
      upstream.pathname = url.pathname.replace(/^\/desktop/, "") || "/";
      return getContainer(env.SHARPPY_API).fetch(
        switchPort(new Request(upstream, request), 6080),
      );
    }

    return getContainer(env.SHARPPY_API).fetch(request);
  },
};
