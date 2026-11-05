// Runs only for requests that match no file in _site/ (files are served without it).
// The flasher keeps its selection in the URL path (/flash/<device>/<role>/<version>), so serve
// the flasher page for any path under /flash/.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Local preview only (dev.sh sets PREVIEW): firmware isn't downloaded at build time,
    // so fetch it from where the full build would have copied it.
    if (env.PREVIEW) {
      let m = url.pathname.match(/^\/flash\/fw\/([^/]+)\/([^/]+)$/);
      if (m) return fetch(`https://github.com/${env.FIRMWARE_REPO}/releases/download/${m[1]}/${m[2]}`);
      m = url.pathname.match(/^\/flash\/firmware\/([^/]+)$/);
      if (m) return fetch(`https://flasher.meshcore.io/firmware/${m[1]}`);
    }

    if (url.pathname.startsWith('/flash/')) {
      return env.ASSETS.fetch(new Request(new URL('/flash/', url), request));
    }
    return new Response('Not found', { status: 404, headers: { 'content-type': 'text/plain' } });
  },
};
