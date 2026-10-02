import type { Root } from "mdast";
import { visit } from "unist-util-visit";

/**
 * Remark plugin that renders Markdown images as their alt text, so an answer never
 * makes the browser load a resource from another origin (FR-046).
 *
 * @returns The tree transformer.
 */
export function noRemoteMedia() {
  return (tree: Root) => {
    // Replace every Markdown image with its alt text, so nothing is fetched
    visit(tree, "image", (node, index, parent) => {
      if (parent === undefined || index === undefined) return;
      parent.children[index] = { type: "text", value: node.alt ?? "" };
    });
  };
}
