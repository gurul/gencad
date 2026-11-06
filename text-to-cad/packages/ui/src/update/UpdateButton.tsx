import { Download } from "lucide-react";
import { useId, useState, type ComponentProps, type ComponentType } from "react";
import type { Popover as PopoverPrimitive } from "radix-ui";
import { Button } from "../primitives/button.jsx";
import { Popover, PopoverContent as PopoverContentPrimitive, PopoverTrigger as PopoverTriggerPrimitive } from "../primitives/popover.jsx";
import { TooltipHint } from "../primitives/tooltip.jsx";
import { useI18n } from "../i18n/index.js";
import { UpdateCard } from "./UpdateCard.js";
import type { UpdateNotice } from "./useUpdateNotice.js";

// The popover primitives are JavaScript, and forwardRef leaves them no props a type can see: theirs are Radix's.
const PopoverTrigger = PopoverTriggerPrimitive as unknown as ComponentType<ComponentProps<typeof PopoverPrimitive.Trigger>>;
const PopoverContent = PopoverContentPrimitive as unknown as ComponentType<ComponentProps<typeof PopoverPrimitive.Content>>;

/**
 * A newer text-to-cad, as the blue update button: a host hands it to the viewer (`update`), which
 * draws it first among the navbar's controls, an icon, over every file and over the home, while
 * this install is behind (`cadgen/updates.py`, which tells only a copy installed by hand). It opens
 * the update card
 * (`UpdateCard`) in a popover, until the person closes it, sends the prompt or clicks away; nothing
 * there is an answer the server keeps, so the button stays until the update lands.
 */
export function UpdateButton({ notice, send, copy, onLink }: {
  notice: UpdateNotice;
  /** Posts the prompt to the chat, where the host can. */
  send?: (prompt: string) => Promise<void>;
  copy(prompt: string): Promise<void>;
  onLink(url: string): void;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const { t } = useI18n();
  const blue = "bg-blue-500 text-white hover:bg-blue-600 dark:bg-blue-500 dark:hover:bg-blue-400";
  return <Popover open={open} onOpenChange={setOpen}>
    <TooltipHint content={t("update.label")}>
      <PopoverTrigger asChild>
        <Button variant="default" size="icon-xs" aria-label={t("update.toAria", { version: notice.latest })} data-update="" className={`size-6 ${blue}`}>
          <Download className="size-3.5" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
    </TooltipHint>
    {/* The card brings its own surface: the popover is only where it opens. */}
    <PopoverContent align="end" sideOffset={6} aria-labelledby={`${id}-title`} aria-describedby={`${id}-text`}
      className="w-80 max-w-[calc(100vw-1rem)] border-0 bg-transparent p-0 shadow-none">
      <UpdateCard id={id} notice={notice} send={send} copy={copy} onLink={onLink} onClose={() => setOpen(false)} />
    </PopoverContent>
  </Popover>;
}
