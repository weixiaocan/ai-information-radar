# AI Radar Site Starter

This folder contains the public portfolio site starter for the separate `ai-radar-site` repository.

## Bootstrap

PowerShell:

```powershell
cd D:\huangxh\AI_Projects_100\p22_AI_Radar
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_site_repo.ps1 -SiteRepoPath ..\ai-radar-site
```

Then install dependencies inside the site repo:

```powershell
cd D:\huangxh\AI_Projects_100\ai-radar-site
npm install
```

## Local preview

```powershell
npm run dev
```

## Cloudflare Pages

- Framework preset: `Astro`
- Build command: `npm run build`
- Output directory: `dist`

## Social links

Edit [`src/site-config.ts`](./src/site-config.ts) before launch:

- `siteUrl`
- `xiaohongshuUrl`
- `wechatUrl`
