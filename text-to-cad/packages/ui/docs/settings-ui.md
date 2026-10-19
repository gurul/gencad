# Viewer interaction and settings design system

This is the binding contract for the viewer's tools, its file sidebar and its
settings, in both apps. Build from the shared pieces — the
[toolbar button](../src/primitives/toolbar-button.jsx),
[FloatingToolBar](../src/renderers/kit/tools/FloatingToolBar.js),
[SubToolbar](../src/renderers/kit/tools/SubToolbar.jsx),
[ToolPopover](../src/renderers/kit/tools/ToolPopover.jsx),
[FileSidebar](../src/renderers/kit/tools/FileSidebar.jsx),
[ToolStack](../src/renderers/kit/tools/ToolStack.jsx),
[ToolPanel](../src/renderers/kit/tools/ToolPanel.jsx),
[the floating surface](../src/lib/floatingSurface.js) and the
[FileSheet primitives](../src/renderers/kit/inspector/FileSheet.js) — and extend
them rather than recreating their layout in a renderer. Environmental effects
belong to apps through the [host contract](viewer-host.md).

## Ownership and layout

FileViewer owns the navbar — the logo's app menu ([Settings](#settings)) included, built from
the host's `links` and the `appSettings` `CadViewer` hands it — and the file explorer (a
popover under the file's name). RendererShell owns the scene's chrome: the tool strip and
the view's controls at its end (Display, Preview), the sub-toolbar of the tool in hand under
it, the file sidebar, Quick Edit, the view cube and Preview. Renderers supply
their tools, their tools' rows, their sidebar sections and their document state; the shell never
inspects a format's parts, joints or topology. No pick or tool opens or closes the explorer.

| The host (web, desktop) supplies | The shared UI decides |
| --- | --- |
| Where the tab record lives (`TabRecordStorage`: the web's sessionStorage, the CAD app's memory) | The record: its settings (the file sidebar's and tool stack's layout, the appearance, the home's layout) and the view of the file on screen (its camera, Display settings, its playback settings, and renderer slices), what is written when, and what is never stored (`@text-to-cad/ui/tab-store`, `kit/shell/fileView.js`) |
| `navigation.home`, `links` (its version, GitHub, Discord, where a new issue opens, how a link opens), `appSettings` (the person's own settings), `colorScheme` (the person's theme and how it changes) | The navbar's order and look, over a file and over the home, the app menu (one menu in the viewer and on the home) and what a new issue says |
| `host.files`, `fileActions`, `navigation`, `clipboard`, `promptContext`, `promptFiles` | When a copy, capture or open happens and what it carries |
| `host.environment`: color scheme, keyboard `platform`, `reducedMotion` | How the chrome honours them |
| `onError`, for errors the viewer hands up | Preview, tooltips, keyboard scope, the tool strip and sidebar, the camera |

Hosts pass no Preview, chrome-visibility or notification props; there are
none.

- **Navbar.** One row, the same in every app, over every file and over the home. Left: the text-to-cad "C"
  logo, named Menu, the size of the row's icon buttons, with no chevron, which opens the
  **app menu** (see [Settings](#settings)) — a host with no home has it too — then, where the
  host keeps the view's own history (`history`: the CAD app's views, which no browser holds),
  **Back** and **Forward**, two arrows walking it as a browser's do, from file to file and to
  and from the home (a step like a file), each there always and disabled where it has
  nowhere to go; then the open file's name and its ⋯. Each of these that
  is a control (`NAV_ITEM_CLASS`) is transparent at rest, takes the same accent background
  while the pointer is on it and while its menu is open, has a pointer cursor and no tooltip:
  it says what it is. The name
  is that control where it opens the explorer (below), where the host's files can be
  browsed; where they cannot it is plain text. The ⋯
  is the file menu: Copy path, and Reveal in Finder / Show in Explorer / Show in file
  manager, each only where the host can do it, and no ⋯ where it can do none. The name has
  no right-click menu and there are no crumbs. The left's controls sit edge to edge, spaced
  by their own padding alone: the logo's 24px button, Back, Forward and the ⋯ in 20px ones,
  and the name 4px in from its edges, so about 7px separate one glyph from the next. Right, only what a host or a file adds: first, the
  update — a blue download button, there only when the host
  found a newer release, whose menu says the step to it, how this host updates and what
  is new. Then, while a person has put an alert card away: the card's own icon (a circle
  with an exclamation mark, red for an error and amber for a warning, named and hinted by
  the alert's title), which brings the card back and goes with it — the renderer's one
  navbar action. Then, where the host shows the view small (inline in a conversation,
  where the view is the whole viewer), its **Full size**, corner brackets. A CAD file publishes no navbar action but that
  icon. The person's own settings, the theme among them, are never here: they are the app
  menu's.

  *Design note: the strip is for tools; the view's controls are the navbar's.* What a host or
  the file adds (the update, an alert's icon, Full size) is the navbar's right end, and last
  after them the view's own controls, **Display** and **Preview** (`navbarSlot`): they act on
  the whole view, whatever tool is in hand, so they are no tools. In Preview the same place
  holds its own controls, **Preview settings** and **Exit preview**. A host with no navbar has
  them over the view instead: Display and Preview ending the strip after a thin rule, the
  Preview's pair in the view's top-right corner. A new per-file button that is no tool goes
  with them.

  A host's home has the same navbar, with only the logo and its app menu (without Back to
  files) and, where the host keeps the view's history, **Back** and **Forward** at the left
  and, at the right end, the host's update, when there is one, and **Full size**, where the
  host shows the view small — the same buttons, sizes and places as over a file. Under it,
  the page: the TEXTTOCAD wordmark and byline, then GitHub (its mark, a link to the project:
  it is open source), Discord and X, as icon links (GitHub and Discord are the app menu's
  too, X its footer's "Made by"; no light/dark button: Theme is the menu's), then Recent Files with its search, grid/list switch
  and Open where the host has a file chooser: the models opened before, pinned first, as cards
  or rows.
  The update shows only for a release
  later than the version the page names, whatever the host says. A file that will not open
  shows a page under the navbar: "File does not exist" and the file's path, or "Could not
  open that file" and the reason, each with **Go home** where the host has a home. A view
  drawn as a picture (`compact`, the home's thumbnails) has no navbar either, and draws the
  model alone: no tools, view actions, cube or Quick Edit.
- **File explorer** is a popover under the file's name (`FolderExplorer.jsx`), aligned to
  the name's left edge, 18rem wide and never resized, as tall as its rows up to 28rem or
  the room below it: past that its list scrolls. It floats over the view and the file
  sidebar, so opening it resizes and moves nothing. It starts in the open file's folder and
  lists one folder at a time — its subfolders, then its CAD files — in compact rows: one 24px
  line of 12px text each, its kind a small light glyph in one column 5px in from the row's
  left end and 4px before the name (a folder its disclosure chevron, with no folder icon; a
  file its type's icon), as the file sidebar's trees draw theirs. A press on a subfolder opens it
  inline, under itself, its rows 10px further in and hung from a faint line under its
  chevron, read once when it first opens; another press closes it, and Right and Left do the
  same from the keyboard. A double-click opens it in the explorer's place, as a crumb does —
  the breadcrumb then names it. The breadcrumb is
  as many of the last three folders as fit whole: every crumb is its folder's whole name, the
  farthest giving way first to the "…" (an ellipsis icon), which lists every folder above the crumbs to jump to,
  and only the folder it is in, left alone beside the "…", is cut (its name a hint while it
  is). The folder it is in reads in the foreground color, the others muted; there is no up
  arrow, and the open file is highlighted, the list opening scrolled to centre its row, once (a
  long folder's too). Opened, its filter has the keyboard, so typing
  finds a file at once; on a phone the explorer itself holds focus, keeping the keyboard
  down. "Filter files..." under the breadcrumb searches
  every file nested under the folder (the server's bounded search, debounced 150ms, each
  keystroke cancelling the search before it); a search that stopped early says "Stopped
  early. Keep typing to narrow the search." Up and Down move between the filter and the
  rows on screen, the rows of a folder open inline among them. A pick opens the file and
  closes it, as do Escape and a press anywhere outside it.
- **Tool strip** at the top centre, 8px down, never wider than the view less 8px at each
  side (it wraps before it would be): the tools, left to right (with no navbar, then a thin
  rule and the view's controls, **Display** and **Preview**: below). 24px tiles with 14px icons,
  an even 4px apart, a tool's chevron touching its button, in a 34px row (`FloatingToolBar`,
  `data-cad-toolbar`). A file with no tools has no strip. On a phone
  ([mobile](#the-file-sidebar-and-the-tool-stack)) the tiles are 36px with 18px icons, a chevron
  20px wide, in one row that never wraps. Centre it on the viewport whenever it fits;
  clamp its position to keep 8px from the edges and from the file sidebar's tile at its left.
  Its available width still uses all the room after that tile. What does not fit goes, from the
  strip's end (the view's controls where the strip has them, then the tools from the last), into **More tools** (an ellipsis, last), a tool a row ticked while it is
  in hand and Display opening its popover from More (`touchStripFit`).
- **Sub-toolbar** under the strip, 8px below it, centred: the tool in hand's one row of
  controls (`SubToolbar`, `data-cad-sub-toolbar`), there for as long as the tool is up (see
  [Tools and lifecycle](#tools-and-lifecycle)). Select and Measure have none. On a phone its
  buttons are the strip's 36px tiles and its sliders as tall, the slider rows 20rem wide.
- **Tool stack** under the sub-toolbar, in the same centred column: a renderer's own
  `toolPanels`, where it hands any (see
  [The file sidebar and the tool stack](#the-file-sidebar-and-the-tool-stack)). The column
  stops 8px above the cube's line (`VIEWPORT_STACK_BOTTOM`), so it never runs past the
  view.
- **File sidebar** at the top-left, 8px in: a toolbar of tiles, one per section of what there
  is to read of the file — a STEP assembly's Model tree, a robot's Links, Position, an SDF's
  metadata, the routines' Animation — whatever tool is in hand; a tile opens its section in a
  panel under the tiles, one at a time, down to 8px off the view's bottom at most. On a phone it
  is one tile, opening one panel with the sections as tabs (see
  [The file sidebar and the tool stack](#the-file-sidebar-and-the-tool-stack)).
- **Quick Edit** at top-right, 8px in, a STEP's or a robot's: the box of the note a
  person writes to their agent, there only while something is picked, drawn or measured
  (see [Quick Edit](#quick-edit)). The rest of the right side of the view is clear.
- **View cube** at bottom-right, 2px from the right and 8px off the bottom so the axes
  drawn in its lower corner never touch the edge (`VIEWPORT_CUBE_BOTTOM`), in a 6rem area:
  enlarged face/edge/corner hit areas and neutral hover and XYZ guides. A host whose own
  control floats over that corner lifts it clear with `--cad-viewport-corner-bottom`, the
  room that control takes from the bottom edge. A host can instead anchor it at bottom-left
  with `--cad-viewport-corner-left: 2px` and `--cad-viewport-corner-right: auto`.
  Codex's tab presentation uses this for all its views to avoid the floating composer.
  Preview omits it, and so does a phone.
- **Display and Preview** end the navbar, for a 3D file (`data-view-controls`, the box
  FileViewer hands the renderer as `navbarSlot`): **Display** (the active mode's sphere: see
  [Display settings](#display-settings-and-section-primitives)) and **Preview** (a play
  triangle, the way into Preview), the navbar's icon buttons, hinted below them. They are no
  tools: pressing one leaves the tool in hand as it is. Display's dropdown opens down from its
  button, aligned to its end, never taller than the viewer below it. A view that is not 3D has
  none of them, and neither does a view drawn as a picture or one that is loading or failed to
  load; in Preview the same place holds its own controls (see
  [Preview](#camera-animation-and-preview)). With no navbar (a host showing the view
  alone) they end the tool strip after its rule, and Preview's stand in the view's top-right
  corner.
- **Nothing sits at the bottom centre**, in the tools view or Preview: a file's routines
  play from the file sidebar's Animation section (see [Preview](#camera-animation-and-preview)).
- **Model update status** sits under the strip and its sub-toolbar, centred, and where
  there is no strip (Preview, a compact view, a load) at the top centre, in the strip's
  34px row, in every host. It is renderer chrome: the navbar carries no status. On mobile
  it is a tappable progress icon whose popover names what is loading.

## Tools and lifecycle

| File | Tool strip, left to right |
| --- | --- |
| STEP | Select, Annotate, Measure, Explode (two or more parts), Clip; then Display and Preview |
| URDF / SRDF / SDF | Select, Annotate, Measure, Clip; then Display and Preview |
| GLB | Select, Annotate, Measure, Explode (several rigid nodes that draw), Clip; then Display and Preview |
| 3MF | Select, Annotate, Measure, Clip; then Display and Preview |
| STL | Select (in hand, the view's navigation: an STL picks nothing), Annotate, Clip; then Display and Preview |
| DXF | Select (in hand, and the view's hand: a drag pans, a tap picks an entity), Annotate, Measure; no view controls: a drawing is 2D |

There is no activity dot. A thin rule parts the tools from the view's controls, which
are no tools (see [Ownership and layout](#ownership-and-layout)). Position is no tool:
its knobs are Select's, while Select's filter picks Position, and its controls are a
section of the [file sidebar](#the-file-sidebar-and-the-tool-stack), and so is Animation, where
the file's routines play (see [Preview](#camera-animation-and-preview)). A file with no tools
and no 3D view has no strip at all.

**A tool the file cannot offer is not on the strip**: never shown disabled.
Renderers leave it out of the `tools` they hand over; `FloatingToolBar` draws
what it is given. Until a file has loaded, what it offers is not known: a tool
that depends on it (Explode) is shown idle meanwhile, a robot's filter offers
Position meanwhile, and the whole strip is disabled while loading. Unavailable and
idle are different states.

One tool owns pointer input, and it alone is lit on the strip. An effect a person set —
an explosion, a cut, a pose — stays on the model once its tool
is put down, with nothing on screen for it but the model. **A press on the tool in hand
does nothing**: a tool is put down by taking up another (Select, most often), or by Escape, which
takes Select up. A press on
Explode or Clip with its effect set takes it up again, as it is; unset, it starts neutral.

| Tool | Pressing it | Its sub-toolbar | Leaving it |
| --- | --- | --- | --- |
| Select | The default tool of every 3D file but an STL; picks what its filter ticks, or a GLB's nodes, a 3MF's objects (Shift adds; Delete deletes annotations and measurements); what is picked is Quick Edit's chips | None: its filter is the chevron after its button | The selection stays, lit and in Quick Edit, under any tool |
| Annotate | Draws on the view | Its tools, what is drawn next, Undo, Redo and Clear annotations (on a phone, the menu of a chevron after its tile instead) | The annotations stay in the model, their chip in Quick Edit; the tool in hand stays, the strip's Annotate showing its icon |
| Measure | Arms picking between points on the model (a STEP's exact vertices, edges and faces; a mesh's triangles, approximately, in its file's unit; a drawing's ends, centres and lines, in the unit it declares, else "units"); each result a chip in Quick Edit, in its colour | None | Unfinished picks are cancelled; completed measurements stay, Quick Edit's chips |
| Explode / Clip | The effect as it is set, or neutral; an edit applies it (Explode's, as a motion: see below) | The slider, its amount beside it, Reset (Clip's: its axis first, whose dropdown holds its settings) | The effect stays on the model |

**One motion at a time.** Every tool's state stands beside every other's — the selection,
measurements, the annotations, Clip — except the two that move the parts: **Explode** and
the **Position** pose. They replace each other: taking up Explode puts the pose back at its
default, and using Position (a knob dragged, a value set or a named pose chosen) takes
Explode off, with nothing set aside to come back. While the model is exploded there are no
knobs. Put down, Explode keeps its explosion under any other tool until Position is used. A
routine played from the Animation section is the third motion: playing it puts Explode and the
pose back at rest, and using either puts the routine back at rest; paused, its frame stays on the
model as a pose does. Preview's routine is its own and moves nothing of the tools view's.
Another file has the motions its tools have, under the same rule, decided by value
(`kit/tools/model-effects/motionExclusion.js`): a GLB's Explode, routine and Clip; a robot's
Position and Clip.

A tree is the file sidebar's, on screen under every tool; a pick in it takes Select up
before it acts.

**Removing an effect.** Explode's and Clip's sub-toolbars end in
Reset ("Reset explode", "Reset clip"): always there, disabled while there
is nothing to take away, it removes the effect — the amount back at zero, nothing else (Clip's
axis and its settings stay as set) — and leaves the tool up. Position's way back is its Pose row's Default. A
measurement's chip X deletes it; the Annotation chip's X clears the annotations.

**Select is the one tool with a menu on the strip**: the chevron right after its button
(`ToolSettingsMenu`'s "chevron" trigger, `kit/tools/ToolModeMenu.jsx`), a small button of
its own as tall as the tile and touching it, lit by its own hover and while its menu is
open, never with the tool. A press on any other tool is its only action. Whatever a tool can
be set to while it is up is its sub-toolbar. A dropdown is ordinary — under its own button,
free to overlap the view — and closes with no exit animation, so a quick second tap (touch
included) always reaches its trigger. Choosing a value closes it; ticking an option leaves
it open, as do Clip's axes and the app menu's Theme. Menu checks sit on the right. The other dropdowns over the viewport are Display,
the sub-toolbars' (Clip's axis and settings, Annotate's colour, weight, line style and placement), its
context menu, and the Animation section's routine and Playback settings (`PlaybackMenu.jsx`, on
`ToolPopover`). Preview's settings are a panel, not a dropdown (see [Preview](#camera-animation-and-preview)).

**Select's filter** (`kit/tools/select/SelectFilterMenu.jsx`), as a CAD tool's selection
filter is: the chevron's dropdown, headed "Selection filter", then **Select all** — ticked
when every kind is, a dash (indeterminate) when some are; pressing it ticks every kind, or,
with every kind ticked, none — then, after a rule, a checkbox per kind of thing Select picks,
each with its glyph and each on its own. A STEP's (`SelectionModes.jsx`): **Parts** (a whole
cube; an assembly's only — a part file's filter offers none, and a press that reaches no face
or edge picks the whole part), **Faces** (a faint cube, its top face filled), **Edges** (a
faint cube, one edge heavy), **Position** (where the file has joints to move: its knobs),
**Annotations** and **Measurement**. A robot's: **Links** and **Position** (where a
joint can be driven). Every kind is ticked when a file opens; the filter holds while the file
is open, across updates of it, and another file starts with every kind. Ticking leaves the
menu open, so several change in one go, and takes Select up. The chevron's name says what is
picked ("Selection filter: everything", "Selection filter: Faces, Edges", "…: nothing").
Select's button is the pointer, whatever the filter. After another rule, a STEP's filter ends
in how a face or edge pick grows, each with its glyph and independent of the filter and of
each other: **Group edges** (the connected edges with a picked edge), shown while Edges is
ticked, and **Group faces** (the smoothly joined faces with a picked face), shown while Faces
is; a hidden one keeps its choice for when it shows again.

The geometry ticked is picked as one mode (`step/workbench/selectionFilter.js`'s
`selectGeometryMode`): Parts with Faces or Edges, a press takes the face or edge it lands on
where the part's topology can be picked, and the part elsewhere; Parts alone, the part;
Faces or Edges without Parts, that topology alone. The mode sets the model tree's shape:
with Parts and Faces or Edges, or no geometry at all, it is the person's own (put back as it
was when they left it, with the owners of what is still selected kept open); Parts alone
opens every assembly and shuts every part; Faces or Edges without Parts open every assembly. A
part is a leaf in every shape: nothing opens under it, and a face or edge picked in the
viewport is revealed at its part's row. Outside the person's own shape the disclosure is
locked (chevrons shown, not pressable) and Expand/Collapse leave the row menus. Under Faces
or Edges a part's topology is asked for as its row comes on screen in the tree, never for a
whole large assembly at once; a viewport press on a part not yet loaded loads that part and
picks, and the model tree's heading says "Loading…" meanwhile. In a large assembly (more than 300
rows of assemblies and parts, `LARGE_TREE_ROWS`) a part's row coming on screen asks for
nothing: the pointer resting on the part in the viewport (150ms) or pressing it asks.

**Sub-toolbars** (`kit/tools/SubToolbar.jsx`): the tool in hand's controls, one row hung
under the strip, centred, 8px below it, on the strip's surface, its buttons the strip's
24px tiles, its groups — what the tool does, how it looks, what it can undo — parted by a
thin rule. It stays up for as long as its tool does, and has no heading: the tool's lit
button above names it. Explode's and Clip's are one shape — what leads
the slider, the slider, its value right beside it and only as wide as
its text, the tool's actions (neither has any), then Reset, last, at the same spot in both,
with no rules — and one width (`SLIDER_SUB_TOOLBAR_CLASS`, 202px; a phone's 320px). The slider
takes the rest of the row. A tool's options never sit in the row as checkboxes, labels or
buttons of their own, which would squeeze the slider: they are the dropdown of what leads it
(Clip's axis).

**Annotate.** Its sub-toolbar, "Annotation controls", while Annotate is up
(`annotation/toolbar.jsx`'s `AnnotationToolbar`): **Annotation tools**, a button each — Pen,
Line, Arrow, Rectangle, Ellipse, Text (a mark put down in place) and Eraser — then a rule and
**Annotation style**, what is drawn next, each a dropdown whose button shows its value, no
chevron: **Color** (a grid of swatches, unnamed but for assistive technology: the neons and
one neutral that reads against the viewer, white in dark mode and near-black in light, then
the colour wheel, which opens the system's colour picker for any other colour, kept once the
picker closes), **Stroke width** (Thin, Medium, Bold — a shape's 1, 2 or 4px, the pen drawn to
look the same weight, its glyph a dot 3, 5 or 7px across) and **Line style** (Solid, Dashed,
Dotted — a shape's line; the pen's freehand ink is always solid; its glyph a diagonal line
drawn in the style), each a row of glyphs alone, the current one marked, and **Placement**
(**Draw on surface**, the default, its glyph a sphere: ink carried with the part under it;
**Draw on plane**, on a plane facing the view through the orbit point, on no part, its glyph a
plane), its glyphs with their names; then **Annotation history** — **Undo**, **Redo** — and
**Clear annotations** (the trash), each disabled while there is nothing for it, with no rule
before them. In a view narrower than 32rem the seven tools and the seven after them are two
rows, column for column, with no rule. Annotate has no Select or Pan of its own (Select picks
annotations, a right drag or Space orbits). Never a restyle of ink already down: the
annotations Select picks have their own bar, a small floating toolbar on the tool strip's
surface just above them — Color, Stroke width and Line style dropdowns, Fill for a closed
shape, a rule, Delete. An update of the model forgets the annotations too, their history with
them (Undo has nothing to bring back), and leaves Annotate the tool, on the tool, colour,
weight, line style and placement in hand. The pen and the shapes share one default stroke
width. The annotations have no panel: while there are any they are Quick Edit's
**Annotation** chip (its X clears them), and while Annotate is up the copy shortcut writes
the view with its annotations to the clipboard as a PNG. A first stroke opens
[Quick Edit](#quick-edit), whose header says **annotation** while there is ink. Annotate
disables the cube without hiding it.

**Measure.** It has no sub-toolbar and no menu: it measures between points on the model,
snapping to no edge or face, and its button is the ruler. Each completed measurement
is a chip in [Quick Edit](#quick-edit): the ruler in the measurement's own colour (the
colour of its line on the model) and its reading; its X deletes it, resting on it lights
its line and labels it, and its card is the full reading (the distance, the angle where
there is one, the delta along each axis, what each end bound to). Measurements stay under
every other tool; a press on Measure while it is up does nothing.

**Explode and Clip** have no enabled checkbox, and their sub-toolbars are drawn alike.
Explode's: its slider, the amount (a percentage), **Reset explode**. Clip's: its axis — a
borderless button reading the axis in hand, "X ⌄", lit while its menu is open — its slider, the
amount, **Reset clip**. The axis's dropdown holds all of Clip's settings, on Display's surface
and in its type, as narrow as its content, with no heading and no glyphs: first X, Y and Z, a
compact group of the app menu's Theme buttons (24px squares, its radius, no track) in a row as
tall as an item (a phone's 40px, as Theme's row), the axis in hand in the accent a highlighted
item wears; a rule; then two of Display's `DropdownMenuCheckboxItem`s, plain text with the check
at the right: **Part colors** (ticked by default: each section cap in its
part's normal colour, without hover or selection tints; unticked, every cap one amber) and
**Reverse** (unticked by default: which side of the plane is kept). Caps stay opaque, a
transparent part's too. A press on any of them leaves the menu open, and none of them applies a
cut; on a cut, a new axis or Reverse turns it keeping its share. They are settings of the
file's view (`clip.axis`, `clip.partColors`, `clip.invert`, stored and restored with its
display), kept across tools, by Reset clip and by taking up an unset Clip. Explode opens at 0%, Clip at no
cut; an edit applies the effect, and the slider back at zero removes it. An axis alone is not
an effect. The view settings own both effects, so a mode reset preserves them and a restored
effect reappears on the model. Clip's slider, left to right, cuts deeper through the original
bounding box; pose, animation and Explode never redefine the range. It shows the share cut
away, while the view stores where the plane stands (`clip.at`, in millimetres), so a model
edit leaves the plane where it was and the slider reads 0% or 100% if the plane ends up
outside the new box. Explode is offered only where there are parts to separate: a STEP
assembly and a GLB of several rigid nodes. A STEP part file has no Explode tile, as it has no
Model tree (`STEP_PART_VIEW_FEATURES`).

## The file sidebar and the tool stack

**The file sidebar** (`kit/tools/FileSidebar.jsx`) holds what there is to read of the file,
whatever tool is in hand — the strip is for using tools, the sidebar for reading the file: a STEP
assembly's **Model tree** (a part file, whose tree would be its one row, has none), then
**Position**, where the file has joints to move; a robot's **Links**, an `.sdf`'s **SDF**, then
**Position**, where a joint can be driven; a drawing's **Layers**, where it has four or more
layers or any block reference (a flat pattern's CUT and BEND has none): each layer's pen, name,
entity count and eye, its block references under it; and, after them, the shell's own **Animation** for a
file with routines (`kit/tools/playbar/AnimationSection.jsx`). A file with none of them has no
sidebar. It is a toolbar of its own at the view's top-left, 8px in, on the strip's line and of
its surface, padding and 24px tiles (`data-file-sidebar-tools`, "File sidebar"): one tile per
section, a tree's a tree icon named for it (Model tree, Links), Position's a spline, Animation's a
clapperboard, any other section's a page named for it. Preview offers its Position and
Animation alone, their tiles bare in its top-left corner; the rest stay mounted, out of sight.

- **One section at a time.** None is open as a file opens. A tile opens its section in a panel
  under the toolbar, 8px below it, and is pressed while it is open; another tile opens its
  section in the panel instead; a second press of its tile closes it, and so does the X that
  ends the section's head. The panel slides in from the left as a section opens with none open
  before, and back out as the last closes (200ms, none under reduced motion); from one section to
  another it stays where it is. Closed, the panel is out of reach (`inert`). Every section stays
  mounted, open or not, so a tree keeps its expansion, search and scroll. Nothing folds: a
  section is its head and its body.
- **Sections.** Each section is a `ToolPanel` drawn as one: a 24px head — its name 12px in from
  the panel's edge, what its body puts there (`ToolPanelHeadAction`: Position's and Animation's
  Reset), then its X — and its body. A tree's head is its filter instead of its name, the X
  after it. The section is its content's height and the panel as tall as it is, up to its cap;
  past that the whole panel scrolls, as one, the head pinned to its top
  (`data-pinned`). A tree's rows are mounted as that scroll brings them into view
  (`kit/inspector/VirtualRows.jsx`).
- **Filter.** A tree is headed by its filter ("Filter model", "Filter links": "Filter…"), in place of a title,
  always there, a tree row's 24px and 11px text, its icon over the rows' glyph column
  (`primitives/tree-filter.jsx`'s `TreeFilterInput`, `dense`), its X clearing it once something
  is typed, Escape too. The model tree's filter is followed by "Loading…" while a part's faces load
  and **Show all** while parts are hidden. Every tree's search is one ranked flat search
  (`kit/inspector/modelTreeSearch.js`).
- **Size, each section's own.** A section's panel opens a tool panel's width
  (`TOOL_PANEL_WIDTH`, 164px) and as tall as its section, capped at the room under the toolbar.
  It is sized from its bottom-right corner alone, by Quick Edit's grip (`kit/tools/ResizeGrip.jsx`):
  width and cap together, by pointer, or by keyboard (a separator named "Resize file sidebar":
  Left/Right nudge the width and Up/Down the cap by 16px, Home and End take both to their
  bounds). Its width runs from 120px (`FILE_SIDEBAR_MIN_WIDTH`: room for a heading's name and its
  buttons; a tree's names truncate) to half the viewer, its cap from 64px to its room. One write,
  when the gesture lets go (or per key), never per pointer move; each section keeps its own size
  (`sidebar:<id>`), so the model tree may be wide and tall while Position stays narrow.
- **On a phone** the sidebar is one touch tile, **Sidebar** (a panel icon,
  `data-file-sidebar-toggle`), at the left of the strip's line, the strip padded clear of it on
  both sides and keeping to its tools (`FileSidebar`'s `phone`). It opens one panel on the section
  last open (the first, at first): its top a row of tabs, one per section with its tile's icon
  (shadcn's `ToggleGroup`, `data-file-sidebar-tab`), and the panel's one X at that row's right end
  (a section's head then has none; a panel of one section has no tabs and keeps its head's X).
  The panel runs down to the view's bottom inset, or is as tall as its section if that is less,
  stopping above Quick Edit's peek (`--cad-quick-edit-peek`), at a phone's own width (288px,
  within the view's inset), with no grip. Its text is the panel's one size (13px, as the
  Display menu's), its tree rows 36px with 16px glyphs, its filter, dropdowns and value fields
  32px (`globals.css`). In Preview its tiles are its top-left's, as on a desktop.
- **The layout is the person's.** The section sizes are one of the tab's settings, across its
  files (`CadPreferences.toolStack`: `{ panels: { [id]: { width?, height? } }, collapsed: { [id]: boolean } }`,
  a section's panel under `sidebar:<id>`, kept beside the appearance; any other key a stored
  record carries is dropped). `panels` holds only what a person set; `collapsed` is the tool
  stack's folded panels. Which section is open is not kept: a file opens with none. A new tab (a
  cleared record) puts everything back at its defaults.

**The tool stack** (`ToolStack`) is the column under the strip and the sub-toolbar, centred
with them, for a renderer's own `toolPanels`. STEP and the robot renderer hand none: their
tools' controls are sub-toolbars and what there is to read of their files is the sidebar's.
Its panels follow these rules:

- **Two kinds of panel.** A `resizable` panel is the person's to size, on its own; every
  other panel is *fixed*: one width, its content's height, and no grip.
- **One width.** Every panel opens at `TOOL_PANEL_WIDTH`: 164px, a strip of six tools (six
  24px buttons, 2px gaps, 4px padding and a 1px border). A fixed panel is exactly that wide; a
  resizable one is only ever made wider, up to half the viewer. The panels hang left-aligned
  in the column, each at its own width. Content truncates to fit; it never widens a panel.
- **Heights.** A panel is exactly its content's height — never padded to a minimum. A
  resizable panel has a *cap* the content grows up to and then scrolls inside: it opens capped
  at the stack's own height (`toolPanelDefaultHeight`). A cap is never a floor.
- **One grip, on a resizable panel only**, the sidebar's: its bottom-right corner, Quick
  Edit's grip, moving its width and cap at once, a separator in the tab order named after its
  panel, keyed as the sidebar's is. A folded panel has no grip: there is no height to set.
- **Never past the viewer.** The column stops 8px above the cube's line
  (`VIEWPORT_STACK_BOTTOM`, `calc(6rem + 16px)`). When the panels need more, a `"tree"` panel
  gives way first, down to 128px or its content, then the `"details"` panels together, each in
  proportion to its height, down to 96px or its content; a `"fixed"` panel keeps its height.
  If what cannot give way still does not fit, the column itself scrolls — a panel is never cut.
- **Headings.** A panel's heading row reads as Display's section headings do (11px, regular,
  `TOOL_PANEL_HEADING_TEXT_CLASS`), 28px tall, 8px in: a title, a summary where there is one,
  then at its right end its own actions, the chevron where it folds (up while open, down while
  folded) and an X where it has something to remove. Every small button in a heading is 20px,
  2px apart and 4px from the edge. A panel can end in one full-row button under its body,
  which never scrolls (`footer`, `ToolPanelFooterButton`).

- **Surfaces.** Three, defined once (`lib/floatingSurface.js`), with one border: the
  tool strip, its sub-toolbars and the stack's panels, which stay up beside the model, share
  `FLOATING_CHROME_SURFACE_CLASS` — the background at 30% and barely blurred
  (1px), so the model behind them is easy to make out; every menu and popover
  over the viewport, the app menu and Display included, share `FLOATING_SURFACE_CLASS` (the
  background at 75%, blurred), so their text never competes with the model; and the file
  sidebar, mostly text but up for as long as the file is open, is between them
  (`FILE_SIDEBAR_SURFACE_CLASS`: 55%, a 4px blur).
- **Scrolling.** Every scroll region in the viewer's chrome — the file sidebar, a panel's
  body, the stack's column, the explorer, a menu, the alert card — is the
  `ScrollArea` primitive (`primitives/scroll-area.jsx`, shadcn's): thin overlay
  bars in the theme's colours, shown while the pointer is over the region. No
  native `overflow-auto` scroller in chrome; `src/designSystem.test.js` holds it.
  The home (the model library) is a page, not chrome: it scrolls as a page does,
  with the platform's scrollbar, and only when there is more of it than fits.
- **Nothing opens elsewhere.** A pick shows as Quick Edit's chips; the sidebar is on screen
  under every tool. No pick or tool opens or closes the explorer, on desktop or mobile.

Tree rows inset their backgrounds 4px from the panel's edges, and the search box
shares that inset. A tree in the file sidebar (Model tree, Links) is dense (`TreeRowSurface`'s
`dense`): 24px rows in the panels' 11px text, and ONE light 12px glyph per row in one
column, as the explorer has: a subassembly's or folded group's disclosure chevron, turned down
while open, or a part's box (Links draws its chevrons alone), 4px before the name. The glyph
column starts 5px in from the row's left end (`TREE_ROW_INSET_PX`), centred under the find
field's search icon and as far in as the icons of a row's actions sit from its right end, in the
STEP tree and the explorer alike; each level adds
the explorer's compact indent, 10px (`TREE_INDENT_PX`), its rows hung from a faint line under
their owner's glyph (`TreeRowGuides`), as the explorer's are; its search box is its section's head. An assembly row's
actions, shown on hover and kept while they are on, are **Isolate** then the **Hide/Reveal** eye; a part file has no
Isolate. A Links row that draws something — a link with visuals, or one visual —
has the eye alone, in its search hit too: a link's hides its own visuals, never its
child links, and on a partly hidden link hides the rest. They float over the row's right end rather than taking width from it:
the name runs the row's full width and, while an action shows, fades out half a
rem before them (a mask, `ROW_NAME_UNDER_ACTIONS`), so nothing is drawn behind the
buttons and the row keeps its own colour.
Model and link finds and the explorer's filter share `TreeFilterInput`; the explorer's rows are compact
24px lines, as the trees' are, but in 12px text.

**Mobile** is below 600px of FileViewer width (Material's compact window class) — the one viewer breakpoint
(`useViewerMobile`); chrome never uses window breakpoints, nor the pointer's kind: a small window
is worked as a phone is. What a finger reaches is the gesture's own (`pointerType`): a touch takes an
edge from 20px off (an edge within 16px wins over the face under it), ink, a measurement and the
eraser's ring from 16px (`TOUCH_HIT_PX`), and a joint's knob from 22px; a mouse keeps its few px.
On a phone every slider is a 36px band with a 20px thumb, and the selected ink's bar has 36px
buttons. A pinch zooms at the touch speed from the first gesture after a load. A phone is read at arm's length
and worked with a finger, so its chrome is one step up the scale, after the platforms' own
guidance (Apple's 44pt and Material's 48dp touch targets, an 11pt type floor and 15-17pt body
text, and iOS Safari zooming into any field under 16px): type 12, 13, 14 and 15px for `text-micro`,
`text-tiny`, `text-xs` and `text-ui`; text entry 16px; menu, select and tree rows 36-40px; the
navbar a 48px row of 36px controls; the strip and the sub-toolbars 36px tiles (the strip one row,
**More tools** holding what does not fit; Annotate's controls its chevron's menu, with no row).
The scale is set once, in `globals.css`, for the whole page while a phone's view is on it, so a
portalled menu, select or hint is the same size as the chrome it opened from. There is no view
cube; the file sidebar is one tile at the strip's left, its sections tabs of one panel; and
Quick Edit is a bottom sheet (see
[Quick Edit](#quick-edit)). The explorer is the same popover, never wider than the window less
1rem. The shortcut hint is hidden.
Touch works for every tool: one finger orbits, two pan and
zoom, a tap picks; a pinch, a cancelled pointer or a camera drag is never a
pick.

## Display settings and section primitives

Display is not a tool. Its tile ends the strip after the strip's rule, between Projection and
Preview, and shows the current mode's sphere icon. It opens a stock shadcn dropdown menu
(`DisplayPopover.jsx`): a muted **Display** label, the modes as a `DropdownMenuRadioGroup`,
a separator, then **Grid**, a `DropdownMenuCheckboxItem`. On a phone the strip's **More**
menu has a Display row whose nested submenu is the same list (`DisplayMenuItems`), with no
label. Checks sit at the row's right end. Choosing a mode closes the menu; ticking Grid
toggles it and leaves the menu open (`onSelect` prevents the close). Clicking outside or
pressing Escape closes it. Opening it leaves the active tool and its controls in place. A
2D view has no Display or Preview control.

Display is a choice of mode and the Grid switch, and nothing else: a mode has no settings
of its own, and there is no settings page. The modes, in order, are **Solid** (shaded with
the model's CAD edges, the default), **Shaded** (no edges), **Parts** (Solid with each part
its own colour), **X-ray**, **Hidden line** and **Wireframe**, filtered by the view's
injected capabilities (`viewFeaturesForKind`, `DisplayModeOptions.js`): a STEP assembly
offers all six, a STEP part file all but Parts, and a file without CAD edges (STL, 3MF, GLB,
a robot) Solid, with Parts when it has several parts, objects or links. **Grid** draws the
measuring grid in every mode, off by default. Each row has its icon, the sphere drawn as the
mode draws a model (and a tile of floor grid for Grid). Render is no display mode: Preview
draws the model in Render whatever the file's mode, with its own settings (see
[Preview](#camera-animation-and-preview)). Per-file storage keeps the mode and the grid;
old-shaped stored display settings are dropped setting by setting, never migrated.
Projection is a menu of its own, shared, orthographic by default; Preview's Render resolves
to perspective while preserving the shared choice.

Preview's settings panel (`PreviewSettings.jsx`, its body `PreviewRenderSettings.jsx`) is
the one settings form: Orbit, then Render's Part colours, Lighting, Background and Floor.
It shows all groups under static section headings and dividers, with no collapsible
sections or cascading settings menus. A heading is 24px of regular `text-tiny` in the
foreground colour, a rule above every one but the first. A feature that switches on and off
(Orbit, Floor) is the checkbox at its heading's right end, the title naming it; there is no
separate row for it. While the feature is off its section is that heading alone. Every
setting is one 24px row: its label in a 4rem muted column, its control filling the rest, so
a form's controls start on one line. A label is short under its heading ("Colour",
"Opacity" under Floor); the control's accessible name stays whole ("Floor opacity"). A
dropdown or colour is as wide as its value, at the row's right end. Sliders are shadcn's,
as everywhere, with a committed value field after them. By part's palette is a row of
swatches, then add and remove. Choices use Select controls. Continuous values use compact
slider and committed-number fields; their keyboard input stays with the field. Colours
retain swatches and a custom colour picker. Floor is on by default, at the model's Z=0
plane. A long form scrolls within the available viewer height. A nested Select or colour
picker owns Escape and outside interaction before its parent surface. The last item is
**Reset to default**, disabled at Preview's defaults; it removes only Preview's overrides,
never the display.

Preview's settings use shared settings field primitives under their static headings; other inspector
sections retain their own disclosure rules. Hover, focus and rendering never write
settings. Light and dark are the app menu's Theme.

Type comes from the token scale only (`text-micro` 10px, `text-tiny` 11px,
`text-xs` 12px, `text-ui` 13px, a phone's a step up: see [mobile](#the-file-sidebar-and-the-tool-stack));
no pixel font sizes. Settings controls and the
menu labels use `text-tiny`, regular weight;
panel headings use 12px. Sections use 8px gutters and bottom insets
and 4px row and column gaps. `FileSheetFieldGrid` owns horizontal spacing; its
children never pad again. Menu, select and context-menu typography comes from
the primitives, portals included. Selected values show their icon where it
means something.

Use `FileSheetSliderField` for a useful bounded range with a committed number
input, `FileSheetNumberProperty` for other scalars, `FileSheetColorProperty` for
color with opacity, and ordinary Select controls for choices. Drafts stay local
until Enter or blur; Escape cancels. Clamp at the owner's write boundary, which
sliders and number inputs share. Omit a visible label only where the value or
icon is unambiguous, and always keep the accessible name.

## Settings

Settings are the person's, never a file's, and live in the app menu: one dropdown
(`file-viewer/navigation/AppMenu.jsx`) on the floating surface, 12rem wide, from the
navbar's logo over every file and over the home (FileViewer builds it from the host's `links`, the
`appSettings` `CadViewer` hands it and `environment.platform`, while a model loads and after
it failed to as well). Its rows, a rule between each group, are only
what the host supplies, the person's settings in the order Language, Telemetry, Theme:

- **Back to files**, where the host has a home
  (`navigation.home`): it shows the home in this view. The home's own menu has none.
- **Language**, where the host hands the person's language (`language`, both apps): one row,
  its name and then the language in force, whose submenu offers **Automatic (<the inferred
  language>)** and then each language under its own name — English, 简体中文, 繁體中文, 日本語,
  한국어 — whatever the menu is reading in; a press changes it without closing the menu. The
  row is a setting row like Theme: its name, then the language in force, muted, right-aligned
  before the chevron, centred on the column Theme's last segment and the checkboxes share. A
  phone has no room beside the menu for a submenu: there a press of the same row opens the
  choices under it, in the menu itself (closed each time the menu opens, the chevron turning
  down while they show), and a choice closes them again.
  Automatic is the default: the web infers the language from the browser's languages, the CAD
  app from its host's locale (then the frame's browser languages); Simplified script or
  mainland China and Singapore read 简体中文, Traditional script or Taiwan, Hong Kong and Macau
  繁體中文, any Japanese 日本語, any Korean 한국어, anything else English. A language chosen
  overrides the inference until Automatic clears it. The host resolves the language and hands
  it down as `environment.locale` (`@text-to-cad/ui/i18n`'s `useLanguage`); the shared UI holds
  no locale of its own.
- The host's own on/off settings (`appSettings`), a checkbox item each, in the order they
  come, checked at the right; a press turns one without closing the menu. An info icon after
  a setting's name, where the host gives its meaning (`info`), shows it as a hint to the
  menu's right. **Telemetry**, in both apps: anonymous usage data and crash reports, never
  prompts, models or files.
- **Theme**, where the host hands the person's colour scheme (`colorScheme`, both apps): one
  row, its name and then **System**, **Light** and **Dark** as a segmented control of their
  glyphs (each a radio item, named), the one in force lit; a press changes it without closing
  the menu. The web's System follows the OS and is
  the tab's; the CAD app's follows its host's theme, Light or Dark overriding it for as long as
  the view is open. Neither app has a light/dark button of its own: Theme is the one
  control, the same on the home.
- **Send feedback**, where the host has a tracker (`links.issues`): a link to a new issue
  titled "Feedback: " for the person to finish, naming the version and the platform, with
  no label (what is said may be a bug, a request or a question). Then **GitHub** and
  **Discord**.
- Last, in gray, a footer of two rows: "v<version>", a link to its release notes, and under
  it "Made by @<handle>", the handle a link to the host's X account. A build that is not the release's
  own adds its id to the version: `v0.7.15-dev.b80844940`, the commit it was built from.

Nothing of a file is in it: a file's view is
[Display](#display-settings-and-section-primitives)'s. Every setting is the person's, not a
view's or a tab's: the host keeps it where every view of theirs reads it (both apps: their
settings, `settings.json` in cadgen's state directory), and a view reads it again whenever
the person comes back to the page.

Every string of the chrome reads through `@text-to-cad/ui/i18n` (`useI18n().t`), English
first: `en.js` holds every key, each other locale the same keys (a parity test), and a key a
locale misses reads English. What a file or cadgen says (an alert's own title and message,
a part's name) stays as it was written. The loading and view-update lines are a closed
vocabulary (`kit/status/loadingState.js`), English in the code and said in the view's language
on screen (`kit/status/statusLabels.js`).

## Position and references

**Position** is a section of the [file sidebar](#the-file-sidebar-and-the-tool-stack), its
tile there under every tool, headed "Position": a STEP's where the file has joints to move, a
robot's where a joint can be driven. Its knobs in the viewport are Select's, while Select's
filter ticks Position, and only while the parts are where the pose puts them: over an explosion
Select draws no knobs (the section's controls stay, and using them takes Explode off). Its
heading holds **Reset position** before its X, idle while the joints are at their default. Its
first row is the pose, a dropdown the panel's width (`KinematicsPoseRow`, `data-pose-row`):
**Default**, which puts the joints back, then the named poses, and Custom while the joints are
set by hand. No divider under the pose row and no Reset footer.
Each joint's label sits tight above its
slider in the flexible left column, with a compact value field (24px tall, about
five characters wide, tabular figures; degrees read "90.0°") in the right column
of the same row; joint rows are 4px apart. Long labels truncate with a full-name
hint and never take the slider's width. Every slider in the viewer is shadcn's slider
(`primitives/slider.jsx`), with a 12px thumb (16px on a phone, in a 36px band) and a track a
shade darker than muted, for these dense, see-through panels: a row sizes and places it, never
restyles its track or thumb — but for a joint's, which has no fill (a joint's zero is mostly
mid-range, so a bar from the left end means nothing). Slider thumbs are named after their
joint, and every slider reports its value at its step's precision (never float
noise). Writes pose the model at once.

Position persists across tools, and across an update of the model whose joints and
named poses are unchanged, the named pose chosen included; an update that changed them
starts the pose at the new defaults, never fitting the old values onto other joints.
Default restores the authored
values (an SRDF's home included), stops motion and hands control back to
Position. Using Position takes Explode off, and taking up Explode puts the pose back to its
default ([one motion at a time](#tools-and-lifecycle)); while the model is exploded there are no
knobs. Preview leaves the tools view's pose as it is and never shows it: it opens on the model
at rest, and a pose set there is its own (see [Preview](#camera-animation-and-preview)). Kinematics, named poses and
animation are separate capabilities; the absence of one never leaves empty
controls for another.

What is picked is [Quick Edit](#quick-edit)'s chips, and a chip's card is what a person
reads of it (`kit/tools/quick-edit/ReferenceChips.jsx`). A component or subassembly is a chip
of its own; faces, edges and solids are a chip for each kind on each part — "base · face 3"
alone, "base · 6 faces" for several, however they were picked — so a large selection stays a
few chips. A chip names its reference: its own label when it has one (a part's or
subassembly's name, a named face), otherwise its part and kind ("base · face 3") — never the
raw id, which its card shows under the name. In a STEP the card's rows are the reference's key
measurements, nothing else: a face's area, and a round face's diameter and radius (a torus's
two radii); an edge's length, or a round one's diameter, radius and circumference or arc
length, with an arc's sweep; a part's size and volume; a subassembly's part count, size and
volume; a run on one part, one row each. Its rows are the UI font at `text-tiny`, numbers in
tabular figures — no monospace. A click on a chip copies its references, each naming its file
by absolute path; resting on it lights its picks; its X drops them.

Viewport picks reach individual faces and edges. In an assembly, faces and edges load per part, when first
needed: under a face or edge filter, a press on a part whose faces are not
loaded loads that part alone and then picks what is under the pointer — one
press, with "Loading…" in the model tree's heading meanwhile. Until
then, hovering such a part lights the whole part.
Shift-click adds to a selection in the viewport; Shift, Ctrl or Cmd does in a
tree (robots select several links this way). Double-click, or a row's Isolate,
isolates a component or subassembly; double-click on empty space leaves
isolation, as do the isolation bar's Exit and the lit Isolate. Only topology that
cannot be isolated copies on double-click, and it stays selected.

## Quick Edit

Quick Edit is a person's note to their agent about the file on screen, and the
one way the viewer hands it over: a box at the viewport's top-right, 8px in, on the
floating surface. It is there only while it has something to carry or a note to keep:
nothing stands in for it otherwise, not even a button. Only a view whose picks and
annotations a note can carry has it (a STEP's, a robot's); a compact host gets none, and
Preview puts it away with the tools. While the view loads it is out of sight, its note
and its state kept. It is essential, so no setting turns it off.

The sidebar and Quick Edit keep their corners, 8px in, unless one would reach under the tool
strip or its tool's row: then it starts 8px below them instead (measured, `--cad-sidebar-top` and
`--cad-top-right-top`), so the strip is never covered. They may overlap each other.

On a phone Quick Edit is a bottom sheet, shadcn's drawer as it ships (`primitives/drawer.jsx`,
vaul): full width, non-modal, never swiped away (its X clears it). It opens at a peek of its
handle, header (its title, what goes with the note, the X) and chips, and a pick never brings up
the keyboard. A swipe up, or a tap on its way in (below), takes it to its open stop,
62% of the screen, its note filling what the header and buttons leave, the keyboard in it; a
swipe down takes it back to the peek, what is written kept. Peeking, under its chips is its way
in, a field-like button reading "Describe your changes…" with a pen, which opens it so; its title
is the sheet's heading, a step up the scale. A tap on a chip opens its card (above the chip,
inside the screen) and copies nothing: the card's title copies. Beside the box, on a desktop, a
card opens to the box's left and a click on the chip copies it. It has no grip there.

The box opens 15rem wide, capped to its column, its note growing with what is written up to 10rem. Its
bottom-left corner — the grip every resizable box over the viewport has
(`kit/tools/ResizeGrip.jsx`) — drags it wider to the left and its note taller, for as long as the
box is open: once it closes, however it closes, the next box opens at 15rem again, and
so does another file's. A drag keeps the box at the corner, a frame at a time and
never eased, and renders nothing: the size is written to the box itself, so nothing
else in the viewer redraws under the pointer. Its header is the title, one step up
the type scale ("Quick Edit"); then what goes with the note, in muted text: **N
ref(s)**, the selection counted one by one (a reference naming several picks counts
each; hovering lists their ids, one a line), and **annotation** while there are annotations;
then an X. The file always goes and is not named. Under the header, the note
("Describe your changes"), its border blue while it has the keyboard, and the
buttons at its bottom-right.

While the note is empty the box follows what it would carry: it opens when something
is picked, annotated or measured, and closes when that goes. Every chip leads with its
icon — the Annotation chip's pen, a measurement's ruler in its colour, a reference's pick glyph
(a part's cube, a face, an edge, a vertex) — then its words, and they stand in the order
they came, whatever their kind. A chip's copy pasted into the note is a pill there,
drawn as the chip is, 20px like the note's lines so it sits in its rows without spacing
them out. A click on a pill selects it whole, highlighted in the selection's colour, so
Backspace, Delete or typing replaces it as it would selected text. Its chips are
**Annotation** (its X clears the ink), each measurement (the ruler in its colour and its
reading, with a details card and an X to remove it), then the selection. Annotation and
measurement chips do not copy references or write files. Copy Prompt, Queue and Send
include their data in the snapshot packet; only selection chips copy individual references. A written note keeps it open whatever
is picked, even with nothing picked or annotated, until the X. The X clears everything:
the note, the selection (as a press on the model's background does), the annotations and the
measurements, so the box goes. A note that has gone (Copy Prompt, Queue, Send) clears the same way.
Escape in an empty box is the viewer's Escape (clearing the selection, and so the box);
in a box with a note it only hands the keyboard back to the model.

The person's picks put the keyboard in the note, each one (a pick right after their
primary press in this view), and so does a first annotation stroke once the pen lifts. A
selection an agent or host makes through the live controller (`select`) opens it without
taking the keyboard.

The buttons, left to right, are only those the host can carry out, and the rightmost
is the primary one, which Enter presses (Shift+Enter is a new line). They are the
`Button` primitive in its own shape — 28px squares with its rounded corners, each an
icon with a name and a hint — and every one is solid: the primary in the `default`
variant, the others in `secondary`. Where Copy Prompt is the only one (a host that
takes no message, as the web), it is a button in words, "Copy Prompt" with its icon
first. While there is no note they are disabled, dimmed but still drawn:

- **Copy Prompt** (copy icon), always. It copies the note as text: its references
  spelled as copied references are, and its files by the paths they were saved at,
  since text carries no file.
- **Queue** (list-plus icon), where the destination is a composer: the note goes
  into the context of the person's next message.
- **Send** (up arrow), where the host can post a message: the note goes now, as the
  person's message.

Every prompt captures the current view and the recorded views with remaining ink.
If the current view matches a recorded view, its exact current framing replaces
that entry for this export; otherwise a `current view` job is appended. Text and
selection alone also capture the current view. The packet stores shared input,
annotation and measurements once, with a `jobs` list of view states.
At Copy, Queue or Send, packets up to 1024 bytes of compact UTF-8 JSON are included
in the prompt as JSON. Larger packets are written to system temporary storage as
one `.snapshot.json` and named by path. Drawing, selecting and typing write nothing.
Captured 3D views preserve projection and lens. No PNG is rendered or attached.
To render inline JSON, the receiving agent saves it to a temporary file first,
then runs `cadgen snapshot --job <file>`.


Queue and Send clear the note and what it carries, and so close the box, once the
note has gone. Copy Prompt keeps it all, since nothing has gone yet: its button
shows a tick for a moment. A failure keeps the note and says why in the box. The message is
one format, sent, queued or copied: what the person wrote; then `File: <path>`; then
`References:` and one reference per line; then each file that travels as a file by its
label and path — `Snapshot (cadgen snapshot --job):` — or the compact object under
`Snapshot JSON (cadgen snapshot --job):`.

## Camera, animation and Preview

Cube face, edge and corner clicks turn the view and keep pan and zoom; dragging
the cube orbits. Reloading the page restores the camera the file on screen was left
at, and its Display settings, Explode/Clip, the pose, hidden and isolated parts and
the tree's expansion come back with it. Only the model on screen keeps that view:
leaving it — for another file or the home — drops it, so opening a file,
for the first time or again, fits it at the defaults. An update of the model on
screen keeps its Display settings, Explode/Clip, hidden and isolated parts and its
tree, and the pose while its joints are unchanged. The tool, the selection and
measurements never come back — every open starts in the default tool with nothing
selected.

Zoom to Fit recenters and frames the whole original model at the current angle;
Zoom to Selection frames the selection and is unavailable without one. Both are
STEP context-menu items; the live `resetCamera` command takes the same fit path.

**Preview** (`previewing` in code) is available for every 3D file, animated
or not, and for nothing else: a renderer declares it (`useRendererShell`'s `previewable`: STEP,
GLB, STL/3MF, URDF/SRDF/SDF), and a view whose renderer does not (a DXF, 2D) has no Preview
button, not a disabled one, and never enters it, whatever asks. It is the shell's own state;
hosts neither start nor observe it. Its button is a play triangle ("Preview"), at the navbar's
right end after Display (the renderer's `navbarSlot`; a host with no navbar has both end the
strip). A press covers the view at once
("Preparing preview…", in the scene's backdrop colour) and enters Preview under the cover,
which lifts once Preview's view has presented its first frame, no finer detail is on its way
(the quality is neither preview nor refining) and the studio frame's picture has converged
(every sample drawn: the viewport's `pictureProgress`) — at least 700ms; at five seconds it stops
waiting for detail and lifts on the picture converged, a second later at the latest — fading from
the finished picture (`kit/shell/previewCover.js`). A view the shell set moving, Orbit
on or a routine playing, has nothing to wait for; detail that lands starts the picture again and
is waited for, never read as motion. Preview's scene takes finer detail in grouped steps,
after a quiet moment or every second while it streams (`step/workbench/settledValue.js`), so a
burst of batches restarts the picture once or twice, not per batch. The navbar stays, so its menu and the explorer
still lead to other files; the tool strip, its sub-toolbar, the tool stack and their resize grips, Quick
Edit, joint handles, cube and context menu are gone (`PreviewChrome`, hidden and inert).

Its controls are always there. At the navbar's right end, in Display's and Preview's place:
**Preview settings** (a sliders icon, pressed while its panel is open) and the way out, an X
(**Exit preview**), their hints below them (a host with no navbar has them at the view's
top-right, `PreviewChrome`'s `end`, tiles with no surface under them). Under them, docked at the view's right edge, the settings panel
(`kit/shell/PreviewSettings.jsx`), closed each time Preview opens and put away by its button
or its own X: **Orbit** — its heading's checkbox turns the camera about the model, off every
time Preview opens, and its **Speed** is a dropdown of speeds — then Render's own settings
page (see [Display settings](#display-settings-and-section-primitives)). At the top-left, the
file sidebar offers its **Position** and **Animation** alone, their tiles bare: Preview's own
pose and routine. Escape leaves Preview too, once an open dropdown has closed. Explode and
Clip are the tools view's alone. Nothing sits under the model, nor at the bottom centre.

**Preview is drawn in Render**, whatever the file's display mode: it is a view of its own
over the tools view, drawing the file's Render settings, and the file's own mode and its
settings are left as they are. The tools view never draws Render: no file's mode is Render,
a live `setDisplaySettings` refuses it as it refuses any mode it does not know, and a saved view
left in it reads as the defaults. Render settings edited in Preview are the file's Render settings;
leaving returns the tools view to the file's mode.

**Routines** play from the file sidebar's **Animation** section, in the tools view and the
Preview alike (`kit/tools/playbar/AnimationSection.jsx`): its heading holds **Reset animation**,
which stops the routine and puts the model at rest, disabled while it is; its body is the
routine in hand, a dropdown of the routines where there are two or more, then **Play** or
**Pause**, the scrubber (`AnimationTimeControl`) and **Playback settings** (a cog: the routine's
Speed, a submenu, then Loop and Autoplay). In the tools view a routine is a motion as a pose is
(see [one motion at a time](#tools-and-lifecycle)): paused, its frame stays on the model. A
routine opens at rest (a STEP's does not own the pose: `restingAnimationState`,
`step/workbench/motionRestore.js`). Each view's routine is its own: entering Preview sets the
tools view's untouched and starts its own at rest, playing only under Autoplay (off by default);
leaving throws Preview's away, and the tools view's is as it was left. An update of the model that leaves its routines as they were neither stops nor rewinds
one that is playing; a changed routine starts at rest. Speed and Loop are the file's, one set,
chosen in Playback settings and kept in its view once chosen — until then the routine's own
apply. Orbit's speed (1×) and Autoplay are the file's too, remembered between leaving and
re-entering Preview and across a reload of the tab; whether it orbits is not kept. Another
file has its own, and a file the tab left starts at the defaults again. Nothing of the
routine — which one, its time, whether it plays — is saved. Orbit is not an animation
setting.

**Preview and the tools view are two states.** Entering Preview leaves the tools view's
state exactly as it is — the tool in hand and its sub-toolbar, the Position pose, the routine,
the selection, hidden and isolated parts, Explode and Clip, Measure's results, the annotations,
the camera — and Preview starts clean, from the model as authored: at its opening pose,
every part shown, nothing isolated, picked, hovered, measured, exploded or clipped, its own
camera fitted at the default angle and still, its routine at rest. Leaving it throws away what
was done there — its camera, its pose, its routine — and the tools view comes back exactly as
it was, in the file's display mode, its camera in the projection and lens the Display settings
now hold. Nothing of the tools view is reset to make room for Preview and nothing of the
Preview's is kept: the next one starts clean again. Preview holds this by being a view of its
own (`kit/shell/PreviewView.jsx`): its own viewport, scene, camera, pose and routine, mounted
over the tools view's while it is up and unmounted as it closes, sharing only the page's GPU
device. The tools view's viewport stays mounted throughout and is never told: it draws nothing
while covered and is uncovered with its own last frame. What is not either state's is the file's settings, shared by
both and kept: its Display settings (an edit in Preview's Render settings is the file's
Render settings), Orbit's speed, Autoplay, Speed and Loop.

**Two views, two ways of drawing.** The tools view is drawn for working on the
model: the scene quality its settings resolve to, and a lower pixel ratio while
the camera moves so a gesture stays responsive. Preview's view is drawn for looking at
it, in Render (`kit/viewport/previewViewScene.js`): one scene-quality tier up (Interactive to
Standard, Standard to High — a higher idle pixel ratio, and at High larger shadow and
environment maps, at the same meshes), its full pixel ratio kept while it orbits, and nothing
of the tools view's (no picking, overlays, cube or tool effects). Neither changes a Display
setting. Render's studio code and environment are prepared a moment after a model is on screen
(`useRendererShell`'s `previewPrepare`), into the GPU device's cache Preview draws from, so
entering Preview has less to do — on a GPU. On a software renderer (SwiftShader, llvmpipe:
the viewport's `softwareRendering`), where that compile would hold the page for seconds unasked,
nothing is prepared ahead: Preview prepares as it is entered, under its cover.

## Keyboard

Escape and Copy belong to one viewer: the one with focus, or the one last
pressed in while focus is on the page. Editable targets keep their own keys.

- **Escape**, innermost first: an open popup in this viewer (a menu, the app menu
  included, a Select, a color picker, Display, the explorer) closes itself; then Preview closes;
  then Annotate's canvas spends its own Escape; then the selected ink; then an unfinished
  measurement; then the tool in hand, any but Select, which goes down and takes Select up, what
  it set kept; then the renderer's own (STEP: the selection, then isolation; robots: the
  selection). The file sidebar and the tool stack's panels are
  never Escape's to close.
- **The file sidebar's grip**, and a resizable panel's (its bottom-right corner), is a
  separator in the tab order: Left/Right nudge its width and Up/Down its cap by 16px, and Home and
  End take both to their bounds.
- **Copy** (⌘C or Ctrl+C, and Ctrl+Insert) copies the view with its annotations
  while Annotate is up, otherwise the selection's references — unless a text field
  has focus or text is selected.
- **Quick Edit's box** keeps its own keys: Enter presses the primary button and
  Shift+Enter is a new line. Escape hands the keyboard back to the view and keeps
  a note; in an empty box it closes the box and is also the viewer's own Escape
  (it clears the selection). ⌘C or Ctrl+C with none of its text selected is the
  viewer's copy.
- **Arrow keys and WASD** orbit the viewer that has focus or the pointer over
  it, never every mounted viewport; they do nothing in Preview or with a
  modifier held.

## Tooltips and feedback

Every hint is a `TooltipHint`: compact text, one surface and arrow, a 400ms
delay. No native `title` anywhere in chrome. Prefer one or two words; show a
full technical name only when it is truncated (`overflowOnly`). Quick Edit's buttons, the
strip's buttons (Display and Preview among them), the navbar's right-hand controls (the
update, an alert's icon, Full size), Preview's corner (Preview settings, Exit preview) and the
Animation section's Reset are hinted by name — the strip's hints above their
buttons, the others' below; there is no hint on the navbar's left (the logo,
the file's name and the ⋯ say what they are), on Display's settings button, Playback settings, an X,
the transport (play, pause, the scrubber), annotation tools or labelled text
buttons (Quick Edit's alone say what they do). A disabled, selected or expanded control has none; pressing or leaving cancels a
pending one. A hint appears on focus only for keyboard navigation (a Tab), never
when a closing menu hands focus back.

The viewer shows no toasts or notifications: copy, snapshot and prompt actions
complete silently, the Copy and Quick Edit buttons showing a tick for a moment.
Progress stays in the viewport; a failed action is the
viewport's alert card, whose **Retry** reloads the file and whose **Report Issue**,
where the host has a tracker, opens a new issue titled "Issue: ", labelled `bug`, filled
in from the card. Its **Details** open into a box that scrolls, with a copy icon at the
box's top-right corner, hinted **Copy**: it copies all of the details and shows a tick for a
moment, or, where the clipboard refuses, a line under the box saying so. Errors handed to
the host's `onError` are the host's to show. A card the
model survives (a failed update, a warning beside the model) has an X, **Dismiss**: it puts
the card away for as long as that alert stands, and its icon, first of the navbar's
right-hand controls after the update button, brings it back. The dismissal goes once the alert changes or clears, or
another file opens; with the card back, so does the icon. Preview has no navbar, and so no
icon.

## Verification

Verify state transitions, touch cancellation, keyboard operation, nested popup
dismissal, feature availability, narrow panels and empty or error states.
Camera and kept-tool tests exercise real transitions, not class names. Do not
keep tests for discarded layouts: replace their assertions with coverage of this
contract. `src/designSystem.test.js` holds chrome to the type scale and the one
breakpoint. The core settings semantics are in
[render-mode.md](render-mode.md); update scheduling is in
[view-updates.md](view-updates.md).
