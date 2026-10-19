# Annotation

Annotate is the CAD viewer's own ink, with no drawing SDK behind it. A view has one
annotation: its marks are projected into the model in 3D, so they stay where they
were drawn from every angle. The STEP renderer is the one that offers Annotate
([Annotate](cad-renderer.md#annotate)).

## Pieces

- `annotation/session.js` — `useAnnotationSession`: the annotation's ink, what the tools
  put down next (tool, the last of each family taken up, color, stroke width, line style,
  placement) and the selection. Each add, erase, restyle of the selection
  (`restyle`) or fill of a closed shape (`fill`, joining its group) is one step
  in the file view's history (`renderers/kit/shell/useViewerHistory.js`, 200
  steps, shared with the renderer's own tools; without one the session keeps its
  own). Choosing what is drawn next never touches ink already down.
  `clear()` is a step; `discard()` drops the ink and takes its steps out of the
  history, for a model that changed under it. The session also keeps the views ink was drawn
  in (`views`, "view 1", "view 2"…): `noteView(view)` names the one a mark goes
  down in — a view drawn in before that is the same (`annotation/views.js`'s
  `sameView`: less than 2° of turn, 5% of zoom or pan, nothing else changed),
  or a new one.
- `annotation/views.js` — a view as a prompt carries it, in a snapshot job's own
  words: the camera (always orthographic), Clip when on, the one motion on
  screen (Explode, or the pose off its default as `kinematics` or
  `jointValues`), the parts hidden and isolated, and the picture's size. Never
  how it looks.
- `annotation/toolbar.jsx` — `AnnotationToolbar`, Annotate's sub-toolbar: seven
  tool buttons (Pen, Line, Arrow, Rectangle, Ellipse, Text, Eraser), then Color,
  Stroke width, Line style and Placement, Undo, Redo and Clear. These form one row
  on a wide view and two equal rows below 64rem. The dropdowns use visual choices;
  Placement offers “Draw on surface” and “Draw on plane”. `annotationColors` offers
  neon swatches and a neutral that reads against the theme: white in dark mode,
  near-black in light mode. A native color picker adds a custom color.
  `AnnotationStylePickers` also restyles the selection's ink.
- `renderers/kit/tools/annotate/AnnotationSelectionBar.jsx` — the bar over the ink Select
  picked: its colour, weight and line style, Fill for a closed shape (seeded
  inside its outline as it falls on the screen, `annotation/geometry.js`'s
  `interiorPoint` and `fillMarkAt`, and projected where the shape lies) and
  Delete.
- `annotation/geometry.js` — each tool's mark in screen space:
  - The pen is smoothed as it is drawn, and each point's width comes from its
    pressure (a stylus's own, or simulated from speed with a mouse), using
    `perfect-freehand`.
  - Rectangles get rounded corners.
  - A fill finds the area inside a shape with
    `@text-to-cad/core/lib/annotation/fillRegion.js`.
- `renderers/kit/tools/annotate/AnnotationOverlay.jsx` — the surface over the viewport
  while Annotate is up. It turns every gesture into marks, previews a mark on its
  own canvas as it is made, and puts it into the model when the gesture ends.
  Text is written where the surface is pressed: Enter, or a press elsewhere,
  puts it down as a text mark; Shift+Enter makes a new line; Escape drops it. The
  surface stops the press's mousedown, which would otherwise take the keyboard
  back from the text it just opened.
  Each mark names the view it was put down in. Annotate has no Select of its own:
  the viewer's Select picks ink (`RendererShell.jsx`, through the viewport's
  `annotationAt`), Shift adding to the pick, and Delete and Escape act on it (here too).
  The camera stays the person's between strokes: the wheel zooms, a right or
  middle drag orbits, and while Space is held the pointer is the view's.
- `mountAnnotations(runtime).update(items, selected, hovered)` haloes the ink Select
  picked, a wider line in the selection's blue behind it, and, fainter, the ink
  its pointer rests on (the shell's `hoveredAnnotation`, the marks drawn with it too). Ink draws after the model and its
  highlights (`ANNOTATION_RENDER_ORDER`), so a lit part never paints over it.
- `renderers/kit/tools/annotate/annotation3d.js` — projects a mark into the model.
  - What lies under the marks comes from one render of the parts' depth and
    ids over the marks' bounds, read back. No ray is cast per point: on a large
    assembly that took most of a second per stroke.
  - Every point stays on the ray through where it was drawn, so from that view
    the ink is exactly what was drawn. Only its depth comes from the model.
  - A stroke lies over the nearest of what is within a few pixels of its line,
    so nothing it was drawn over cuts through it. Where it leaves the model it
    carries on in the air from the model's depth there.
  - A fill lies on the surface when all of it is over the model, else whole on a
    sheet in front of what it covers. A text mark stands in front of what it covers.
  - A mark belongs to the part most of it lies on, in that part's frame, so
    Explode and Position carry it, Clip cuts it, and hiding the part hides it.
    Marks drawn as one thing (`group`: an arrow's line and its head) belong to
    the part most of them all lies on, so they never come apart. `touches` lists
    the parts it was drawn over, most first.
  - A mark drawn **in space** ignores the model: every point lies on the plane
    facing the view just in front of the model's bounds, so nothing of the model
    hides it from where it was drawn. It belongs to no part (`part: null`,
    `placement: "space"`), its points are model coordinates, and it stays put
    through Explode, Position and hiding parts. Clip still cuts it. Moved with
    Select, it lands on that plane as the view is then. When every mark is in
    space, the parts are not rendered for depth at all.
  - The projected ink is plain data (`AnnotationItem`): an annotation mark
    (`@text-to-cad/core/common/annotation.js`) with its part's placement as it was
    drawn, kept across scene rebuilds. `mountAnnotations` draws it in a viewer runtime and
    `update` draws only the marks a change adds; the objects and how they follow
    their parts are core's, the ones a snapshot draws an annotation with. The preview
    holds a finished mark until the scene has drawn it. `annotationDocumentOf` writes the
    annotation as an annotation file.

## Lifetime and capture

The live annotation is session-only: it is never written to tab or file state. It
outlives Annotate being put down, because the ink stays in the model and the next
Annotate adds to it. It goes when the person clears it, or when the model it was
drawn on changes.

⌘C / Ctrl+C while Annotate is up copies the view as it is on screen, ink
included, to the clipboard as a PNG.

Quick Edit captures the current view and distinct views with remaining ink when
Copy Prompt, Queue or Send is pressed (`host.promptFiles`). The snapshot packet
includes shared annotation and measurements: up to 1 KiB of compact UTF-8 JSON
travels inline, and larger packets are saved to a temporary `.snapshot.json`.
No images are rendered at handoff. Save inline JSON to a file before running
`cadgen snapshot --job <file>` to render those views over the model or an edit of it.
Annotation and measurement chips do not copy references or save individual files.
Queue and Send clear the annotation with the note; Copy Prompt keeps it.
