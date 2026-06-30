# Boltrig marketing site

The public landing page served at **https://boltrig.io** (and `www.boltrig.io`).
Self-contained static site - no build step. Branding is faithful to the product
console in `../ui` (same ink palette, cyan + indigo accents, IBM Plex Sans /
JetBrains Mono, the bolt-in-brackets mark, the electric-blue aurora).

- `index.html` - the page
- `styles.css` - the styles (design tokens mirrored from the console)
- `favicon.svg` - the mark

## Hosting (jellytot-prod)

Served by the host Caddy straight from a copy of this directory, behind the
Cloudflare tunnel. The console lives separately at `app.boltrig.io`; `boltrig.dev`
redirects here.

```
# /etc/caddy/Caddyfile
http://boltrig.io, http://www.boltrig.io {
	import common-headers
	root * /srv/boltrig-marketing
	file_server
}
```

Deploy = copy this dir to `/srv/boltrig-marketing` on the host and reload Caddy.
