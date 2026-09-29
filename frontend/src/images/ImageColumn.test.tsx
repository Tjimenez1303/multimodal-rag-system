import { fireEvent, render, screen, within } from "@testing-library/react";

import { ImageColumn } from "@/images/ImageColumn";

import { answerWithFigures } from "../../tests/fixtures/answers/sample";

const { primary_image: primary, related_images: related } = answerWithFigures;

function renderColumn() {
  return render(<ImageColumn primary={primary} related={related} />);
}

test("the primary image shows its caption and its document and page below it", () => {
  renderColumn();

  const figure = screen.getByRole("figure", { name: /Figure 4-12/ });
  const image = within(figure).getByRole("img");
  expect(image).toHaveAttribute("src", primary!.url);
  expect(image).toHaveAttribute(
    "alt",
    "Figure 4-12. Shunt generator circuit. faa-powerplant-ch4-ignition-electrical.pdf, page 12",
  );
  expect(image).toHaveAttribute("loading", "lazy");
  expect(image).toHaveAttribute("decoding", "async");
  expect(figure).toHaveTextContent("Figure 4-12. Shunt generator circuit");
  expect(figure).toHaveTextContent(
    "faa-powerplant-ch4-ignition-electrical.pdf, page 12",
  );
});

test("related images form a secondary group in the returned order", () => {
  renderColumn();

  const group = screen.getByRole("group", { name: "Related images" });
  const figures = within(group).getAllByRole("figure");
  expect(figures).toHaveLength(2);
  expect(figures[0]).toHaveTextContent("No caption");
  expect(figures[0]).toHaveTextContent("page 13");
  expect(within(figures[0]!).getByRole("img")).toHaveAttribute(
    "alt",
    "Figure without caption. faa-powerplant-ch4-ignition-electrical.pdf, page 13",
  );
  expect(figures[1]).toHaveTextContent("Figure 4-13. Terminal block");
});

test("an image that fails to load says so and keeps its caption, document and page", () => {
  renderColumn();
  const figure = screen.getByRole("figure", { name: /Figure 4-12/ });

  fireEvent.error(within(figure).getByRole("img"));

  expect(figure).toHaveTextContent("Image unavailable");
  expect(figure).toHaveTextContent("Figure 4-12. Shunt generator circuit");
  expect(figure).toHaveTextContent(
    "faa-powerplant-ch4-ignition-electrical.pdf, page 12",
  );
});

test("a response without images renders no column", () => {
  const { container } = render(<ImageColumn primary={null} related={[]} />);

  expect(container).toBeEmptyDOMElement();
});

test("every figure can be viewed full size and open its page", () => {
  renderColumn();

  expect(screen.getAllByRole("button", { name: "View full size" })).toHaveLength(3);
  expect(screen.getAllByRole("button", { name: "Open page" })).toHaveLength(3);
});
