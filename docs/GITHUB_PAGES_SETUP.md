# Configuration GitHub Pages — LLM Router

## Automatic deployment

The workflow `.github/workflows/deploy-docs.yml` builds the Jekyll site (Cayman theme) from the `docs/` folder and deploys it to GitHub Pages on every push to `main` or `master`.

## Steps on GitHub

1. **Settings > Pages**
   - **Source**: choose **GitHub Actions** (not "Deploy from a branch").

2. **Custom domain**
   - In **Pages > Custom domain**, enter: `llm-router.javid-space.cloud`
   - Check **Enforce HTTPS** once DNS is active.

## DNS configuration

Add a CNAME record at your DNS provider (Cloudflare, OVH, etc.):

| Type  | Name       | Value                        |
|-------|------------|------------------------------|
| CNAME | llm-router | `javid-mougamadou.github.io` |

Propagation may take a few minutes to a few hours.

## Site URL

**https://llm-router.javid-space.cloud**
