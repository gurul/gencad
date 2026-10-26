import { RotateCcw } from "lucide-react";
import { ToolbarButton } from "@text-to-cad/ui/primitives/toolbar-button";
import SubToolbar, { SLIDER_SUB_TOOLBAR_CLASS, SUB_TOOLBAR_SLIDER_CLASS, SubToolbarValue } from "../SubToolbar.jsx";
import { CrossSectionControls, ExplodeControls, clipSummary } from "./ModelViewControls.js";

/** Separated assembly layers, distinct from an expand affordance. */
function ExplodeIcon(props) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="m12 2 8 4-8 4-8-4Z M4 11l8 4 8-4 M4 17l8 4 8-4" />
    <path d="M4 6v2l8 4 8-4V6 M4 17v2l8 4 8-4v-2" />
  </svg>;
}

function ClipIcon(props) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M16 4.5a8.5 8.5 0 1 0 0 15" />
    <ellipse cx="16" cy="12" rx="3" ry="7.5" />
  </svg>;
}

/**
 * Explode and Clip: tools whose effects stay on the model once the tool is put down; the
 * sub-toolbar is the tool's while it is in hand, and nothing of either is on screen after. A press on one in
 * hand does nothing; on one whose effect is set it takes it up again, as it is, and on one unset
 * it starts neutral. Its Reset removes the effect (the amount back at zero, Clip's axis and
 * settings kept), idle while none is set; the tool stays up. (Measure's results are Quick Edit's chips.)
 *
 * Each is offered where the view's features list it (`ViewFeatures`): a renderer decides which of its
 * files have them, and lists Explode only where there are parts to separate.
 */
export function useModelTools({ view, features, store, mesh, disabled, selectedTool, onSelect }) {
  const applied = [
    ...(view.exploded.enabled && view.exploded.amount > 0 ? ["exploded"] : []),
    ...(view.clip.enabled ? ["clip"] : []),
  ];
  // The box Clip's plane is placed in, so its slider maps with exactly that box: the model at
  // rest, its declared box when a package has one (the scene's `restBounds`, which the viewport
  // hands the plane as `zeroPoseBounds`).
  const clipBounds = mesh?.declaredBounds || mesh?.bounds || null;
  const definitions = [
    { id: "exploded", label: "Explode", Icon: ExplodeIcon,
      // Named, as Clip's axis and Animation's Play lead theirs: a bare slider says nothing of what it moves.
      lead: <span className="shrink-0 pl-1.5 pr-1 text-tiny text-foreground">Explode</span>,
      summary: `${Math.round((view.exploded.enabled ? view.exploded.amount : 0) * 100)}%`,
      controls: <ExplodeControls viewSettings={view} onViewSettingsPatch={store.patch} className={SUB_TOOLBAR_SLIDER_CLASS} /> },
    { id: "clip", label: "Clip", Icon: ClipIcon, summary: clipSummary(view, clipBounds),
      controls: <CrossSectionControls viewSettings={view} onViewSettingsPatch={store.patch} bounds={clipBounds}
        className="flex min-w-0 flex-1 items-center gap-1" sliderClassName={SUB_TOOLBAR_SLIDER_CLASS} /> }
  ].filter(tool => features.settings.includes(tool.id));
  // Neutral is the amount at zero, nothing else: Clip's axis and its settings (Part colors, Reverse) stay as set.
  const neutral = id => id === "exploded" ? { exploded: { enabled: false, amount: 0 } } : { clip: { enabled: false } };
  const tool = definitions.find(value => value.id === selectedTool);
  return {
    tools: definitions.map(({ id, label, Icon }) => ({
      // Their own group on the strip, ruled off from the tools that pick.
      id, label, group: "model", active: selectedTool === id, disabled, changed: applied.includes(id),
      icon: <Icon className="size-3" strokeWidth={2} aria-hidden="true" />,
      onSelect: () => {
        if (selectedTool === id) return;
        onSelect(id);
        // Unset, it starts neutral; an edit sets its effect.
        if (!applied.includes(id)) store.patch(neutral(id));
      }
    })),
    // The tool in hand's sub-toolbar (`kit/tools/SubToolbar.jsx`), unnamed — its button is lit on the
    // strip above it: what leads it (Explode's name; Clip's axis, whose dropdown holds its settings too),
    // its slider, the amount beside the slider, then any actions of its own and Reset, which takes the effect away (the tool stays up) —
    // always there, idle while there is nothing to take away.
    subToolbar: tool ? <SubToolbar key={tool.id} label={`${tool.label} controls`} className={SLIDER_SUB_TOOLBAR_CLASS} data-model-tool={tool.id}>
      {tool.lead || null}
      {tool.controls}
      <SubToolbarValue data-model-tool-amount="">{tool.summary}</SubToolbarValue>
      {tool.actions || null}
      <ToolbarButton label={`Reset ${tool.label.toLowerCase()}`} disabled={!applied.includes(tool.id)} onClick={() => store.patch(neutral(tool.id))}>
        <RotateCcw className="size-3" strokeWidth={2} aria-hidden="true" />
      </ToolbarButton>
    </SubToolbar> : null
  };
}
