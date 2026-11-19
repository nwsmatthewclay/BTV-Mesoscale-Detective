import { Container, getContainer } from "@cloudflare/containers";

export class SharpPyContainer extends Container {
  defaultPort = 8000;
  sleepAfter = "10m";
  enableInternet = true;

  envVars = {
    BUFKIT_CACHE_DIR: "/tmp/bufkit-cache",
    BUFKIT_CACHE_TTL_SECONDS: "300",
  };

  onStart() {
    console.log("BTV SHARPpy API container started");
  }

  onError(error) {
    console.error("BTV SHARPpy API container error:", error);
    throw error;
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/__worker_health") {
      return Response.json({ status: "ok", service: "BTV SHARPpy Container Worker" });
    }
    return getContainer(env.SHARPPY_API).fetch(request);
  },
};
