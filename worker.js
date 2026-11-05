// Runs only for requests that match no file in _site/ (files are served without it).
// The flasher keeps its selection in the URL path (/flash/<device>/<role>/<version>), so serve
// the flasher page for any path under /flash/.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith('/flash/')) {
      return env.ASSETS.fetch(new Request(new URL('/flash/', url), request));
    }
    return new Response('Not found', { status: 404, headers: { 'content-type': 'text/plain' } });
  },
};
