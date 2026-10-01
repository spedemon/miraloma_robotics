# Mira adaptive UI architecture

Status: proposed

## Decision

Build one adaptive Mira application with one state model, one set of robot actions, and one semantic document/component tree. Give compact screens a different application shell and workspace composition; do not create a separate mobile application or duplicate the feature UI.

The mobile experience should be organized as four task-focused workspaces:

1. **Move** — direct joint and XYZ control.
2. **Animate** — capture, arrange, preview, save, and upload a sequence.
3. **Dances** — run built-in and saved moves, with Stop always visible.
4. **Robots** — discover, connect, select, rename, update, and inspect robots.

Only one workspace is mounted or visible at a time on compact screens. The currently targeted robot is global context, not a fifth piece of page content. Tapping the target/connection control opens the robot picker as a sheet in portrait or a side panel in landscape.

## Why the current layout fails

The Android application targets SDK 35 and places a full-screen `WebView` directly into the activity. Android 15 therefore lays the app edge-to-edge, but the activity and web content do not consume status-bar, navigation-bar, or display-cutout insets. The header's interactive controls can consequently sit under the status icons and camera cutout.

The web layout has a second, independent problem. At 768 px it changes the desktop row into a column, caps the robot sidebar at 180 px, and leaves Move, Animate, and Dances together in one vertically scrolling control panel. This is desktop content stacking, not a mobile interaction model.

## Product model

### Global shell

- **Safe top app bar:** Mira identity at the start; Help and connection at the end. “Build with us” moves into the overflow/about sheet on compact screens because it is not a primary operating action.
- **Target bar:** one line below the app bar, e.g. `All robots · 3 online` or `Mira Blue · connected`. It opens the robot picker.
- **Workspace:** exactly one primary task, sized to the available safe viewport.
- **Primary navigation:** bottom navigation in portrait; a left navigation rail in landscape. Move, Animate, Dances, Robots.
- **Emergency action:** Stop remains reachable in Move, Animate, and Dances. On compact screens it is a persistent control above the bottom navigation when motion may be active.
- **Diagnostics:** the debug console leaves the normal mobile shell. Put it under Help → Diagnostics, with a copy/share action rather than a persistent collapsed bar.

### Workspace behavior

#### Move

- Default to Joint mode.
- Use four large sliders with 48 px or larger touch rows and immediate value feedback.
- Keep Home and Stop visible without page scrolling.
- Keep XYZ mode off phones in both orientations. Its projections and coordinate model are too dense for a compact touch interface.
- Keep XYZ available on tablets and desktops, where the projections have enough space to remain understandable and safe to operate.

#### Animate

- Portrait uses a compact keyframe strip: pose thumbnails/numbers, duration, Capture, Play/Pause, and an inspector sheet for the selected keyframe.
- Landscape uses the richer multi-lane timeline and is the recommended orientation, but portrait must remain functional. Never lock the whole application to landscape.
- The workspace itself does not vertically scroll. The timeline/keyframe strip owns horizontal scrolling; an inspector sheet owns its own short content scroll if necessary.

#### Dances

- Use a two-column portrait grid and a denser landscape grid.
- Make active/running state unmistakable and pair it with a persistent Stop action.
- Custom moves appear in the same grid with an overflow menu for rename/delete; do not rely on hover-revealed delete buttons.

#### Robots

- Show discovery and connection as a first-class workspace rather than a compressed banner above controls.
- Each row includes name, connection method, status, selection state, and one clear primary action.
- “All robots” is a targeting option, not a discovered device.
- Firmware/setup flows remain modal or step-based and use the full safe content width.

## Responsive layout matrix

| Window posture | Navigation | Robot selection | Workspace composition |
| --- | --- | --- | --- |
| Compact portrait | Bottom bar | Bottom sheet; full Robots workspace for management | Single-column, one task, no page-level scroll where controls can fit |
| Compact landscape | Left rail | Right sheet/panel | Full-height task canvas; Animate gets the rich timeline |
| Tablet / narrow desktop | Left rail | Collapsible side panel | One active workspace, optional secondary panel |
| Wide desktop | Left sidebar or rail | Persistent panel | Active workspace can use multi-panel tools; avoid returning to an undifferentiated stack of all tools |

Use available width and height rather than device names. A reasonable starting point is compact below 720 CSS px, with a landscape-specific composition when width exceeds height and usable height is limited. Validate the actual breakpoint using the smallest supported control sizes and content, not a particular Pixel model.

## Scroll ownership

“No scrolling” should mean no long document containing unrelated tools. Some bounded scrolling remains necessary and accessible:

- the Robots list scrolls inside the Robots workspace;
- the animation timeline scrolls horizontally;
- modal/help content can scroll vertically;
- Move and Dances should fit the safe viewport at normal font size;
- never create nested vertical scroll regions in the main operating path.

## Implementation architecture

### Shared core

Extract the current global variables and direct DOM mutations into small modules with explicit responsibilities:

- `mira-store`: robots, selected target, transport status, current pose, active gesture, animation document, and UI route;
- `robot-service`: the existing Socket.IO/Android bridge boundary and command API;
- `workspace-router`: active workspace and orientation-independent navigation state;
- feature controllers/views: `move`, `animate`, `dances`, and `robots`;
- `app-shell`: safe areas, top/target bars, navigation, sheets, and dialogs.

The first refactor does not require a framework. ES modules, templates, and event delegation are sufficient. A framework migration would add risk without solving the information architecture. The important boundary is shared state/actions versus adaptive presentation.

### One implementation, multiple compositions

Reuse the same feature markup and event handlers where the interaction is genuinely the same. Use CSS Grid areas, feature-level layout classes, and a small posture observer to compose those pieces differently.

For Animation Maker, permit two view components—`AnimationCompactView` and `AnimationTimelineView`—because their information density and manipulation model differ substantially. They must consume the same animation state and dispatch the same commands. This is two presentations, not two applications.

Do not maintain separate `mobile.html` and `desktop.html` files, duplicate IDs, or parallel robot command code. Those would drift quickly and double testing cost.

## Safe-area contract

Treat system insets as an app-shell concern:

1. Keep the Android window edge-to-edge so backgrounds may extend behind system UI.
2. Obtain `systemBars` and `displayCutout` insets in the Activity.
3. Expose them to the web shell as CSS custom properties, with CSS `env(safe-area-inset-*)` as a browser fallback. Use one source at a time to avoid double padding.
4. Pad interactive app-bar content on top/left/right and bottom navigation on bottom/left/right. Background surfaces may continue edge-to-edge.
5. Add `viewport-fit=cover` to the viewport declaration.
6. Recompute on rotation, multi-window resize, and navigation-mode changes.

The top app bar's visual height and its safe-area inset are separate values. The camera/status area must never consume the bar's intended 48–56 px touch height.

## Accessibility and interaction requirements

- Interactive targets are at least 48 × 48 CSS px on coarse pointers.
- Essential actions never depend on hover; this currently affects custom-gesture deletion.
- Sliders support touch without the page stealing the gesture (`touch-action` scoped appropriately).
- Text inputs use at least 16 px text to avoid browser zoom behavior.
- Focus order follows the visible workspace; hidden workspaces use `hidden`/inert behavior, not off-screen positioning.
- Rotation preserves the active workspace, selected robot, pose, and unsaved animation.
- Respect reduced motion and increased font size up to at least 200% without hiding Stop or navigation.

## Delivery plan

### Phase 0 — safety hotfix

- Apply Android/WebView safe-area handling.
- Add safe top and bottom padding in the shell.
- Verify all header controls on Android 15+ portrait and landscape.

This can ship independently, but it does not constitute the mobile redesign.

### Phase 1 — adaptive shell

- Add workspace routing and portrait bottom navigation / landscape rail.
- Move robot selection into a sheet/panel and Robots workspace.
- Remove the mobile stacked sidebar and page-length control panel.
- Move Build with us and Diagnostics out of the primary mobile chrome.

### Phase 2 — feature adaptations

- Recompose Move around Joint mode for portrait and phone landscape; retain XYZ for tablet and desktop.
- Add compact and timeline Animation views over one animation model.
- Rework Dances for touch and persistent Stop.
- Make help/setup dialogs safe-area and keyboard aware.

### Phase 3 — validation and hardening

- Visual-regression screenshots at representative safe viewport sizes.
- Interaction tests for navigation, target persistence, sliders, Stop, and rotation.
- Android instrumentation tests for insets and bridge continuity.
- Manual device checks with gesture and three-button navigation, font scaling, display cutout emulation, split screen, and keyboard open.

## Acceptance criteria

- No actionable control intersects status bars, camera cutouts, gesture areas, or three-button navigation areas.
- Portrait launches into Move with the target context and all primary joint controls usable without navigating a long document.
- Every feature is reachable in one tap from primary navigation.
- Moving between workspaces or rotating never disconnects the robot or loses unsaved animation state.
- Move and Dances have no page-level vertical scroll at the reference compact viewport; Robots and Help have exactly one intentional vertical scroll owner.
- Stop is reachable in one tap whenever a robot action can be running.
- All controls work with touch and keyboard; no essential control is hover-only.
- The same state, transport, validation, and command code serves compact and wide layouts.

## Recommendation

Do not build two UI implementations. Build one adaptive product with a shared core and, where interaction density demands it, two feature-level presentations over the same state. Landscape should be an enhancement—especially for Animation Maker—not a gate that prevents a parent or child from using Mira while holding the phone naturally.
