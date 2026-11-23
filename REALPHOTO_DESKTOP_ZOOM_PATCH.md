# RealPhoto desktop zoom customization (initial patch)

This customization adds mouse-wheel scaling to the transparent avatar overlay.

## Behavior
- Hover the mouse over the avatar and scroll up to enlarge it.
- Scroll down to shrink it.
- Zoom is clamped between 0.35x and 2.5x.
- The chosen zoom is stored in the Tauri webview's localStorage and restored on next launch.
- The zoom is applied as a CSS transform, so image proportions and frame animation remain intact.

## Changed files
- `apps/desktop/frontend/src/routes/OverlayRoute.tsx`
- `apps/desktop/frontend/src/styles/overlay.css`

## Build / verify
From the repository root (Node >=20, pnpm 11.x):

```powershell
pnpm install:safe
pnpm --filter @openmimicry/desktop-frontend run typecheck
pnpm --filter @openmimicry/desktop-frontend run build
```

## Notes
This is an initial zoom patch only. It does not yet add a resize grip, zoom slider in Settings, or persist scale to the backend YAML. It stores the user's overlay zoom in the local webview storage.
