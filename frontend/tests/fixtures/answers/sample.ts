import type { AnswerBody, AnswerImageBody, SourceBody } from "@/client";

/** Hand-written responses for component tests, typed with the generated client. */

const FAA = "9660318f-9004-4fa9-925c-fb616874f516";
const WELDING = "06187a89-5984-40cf-a33b-ccc0a4e07aa8";
const BBOX = {
  left: 72,
  top: 120,
  right: 540,
  bottom: 460,
  origin: "top_left",
} as const;

function source(fields: Partial<SourceBody> & Pick<SourceBody, "unit_id">): SourceBody {
  return {
    rank: 1,
    similarity: 0.8,
    document_id: FAA,
    document_name: "faa-powerplant-ch4-ignition-electrical.pdf",
    section: [],
    pages: [12],
    content_type: "text",
    excerpt: "",
    cited: true,
    citation_number: 1,
    low_confidence_text: false,
    generated_description: false,
    unverified_identifiers: [],
    tables: [],
    figure_ids: [],
    ...fields,
  };
}

function image(
  fields: Partial<AnswerImageBody> & Pick<AnswerImageBody, "element_id">,
): AnswerImageBody {
  return {
    document_id: FAA,
    document_name: "faa-powerplant-ch4-ignition-electrical.pdf",
    page: 12,
    bbox: BBOX,
    caption: null,
    unit_id: "11111111-1111-4111-8111-111111111111",
    url: `/api/v1/documents/${FAA}/images/${fields.element_id}`,
    ...fields,
  };
}

/** An answer with a primary figure, related figures and every kind of source. */
export const answerWithFigures: AnswerBody = {
  status: "answered",
  reason: null,
  answer: [
    "## Shunt generator wiring",
    "",
    "The field winding is connected **in parallel** with the armature [1].",
    "",
    "1. Connect the field across the brushes [2].",
    "2. Adjust the field rheostat, then check `F+` and `A+` [3].",
    "",
    "Compare the terminals in the table [3] and the welder notes [4].",
  ].join("\n"),
  not_covered: "The documents do not give the rheostat's resistance value.",
  citations: [
    {
      number: 1,
      document_id: FAA,
      document_name: "faa-powerplant-ch4-ignition-electrical.pdf",
      pages: [12],
      unit_ids: ["11111111-1111-4111-8111-111111111111"],
    },
    {
      number: 2,
      document_id: FAA,
      document_name: "faa-powerplant-ch4-ignition-electrical.pdf",
      pages: [13, 12],
      unit_ids: ["22222222-2222-4222-8222-222222222222"],
    },
    {
      number: 3,
      document_id: FAA,
      document_name: "faa-powerplant-ch4-ignition-electrical.pdf",
      pages: [14],
      unit_ids: ["33333333-3333-4333-8333-333333333333"],
    },
    {
      number: 4,
      document_id: WELDING,
      document_name: "tm-5-3431-201-10-welding-machine-scanned.pdf",
      pages: [3, 4, 9],
      unit_ids: [
        "44444444-4444-4444-8444-444444444444",
        "55555555-5555-4555-8555-555555555555",
      ],
    },
  ],
  sources: [
    source({
      unit_id: "11111111-1111-4111-8111-111111111111",
      section: ["Generators", "Shunt-wound generators"],
      excerpt:
        "In a shunt generator the field coil is connected in parallel with the armature.",
      figure_ids: ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"],
    }),
    source({
      unit_id: "22222222-2222-4222-8222-222222222222",
      rank: 2,
      citation_number: 2,
      pages: [12, 13],
      section: ["Generators", "Field circuits"],
      excerpt: "The field is energized across the brushes.",
    }),
    source({
      unit_id: "33333333-3333-4333-8333-333333333333",
      rank: 3,
      citation_number: 3,
      pages: [14],
      content_type: "table",
      section: ["Generators", "Terminal markings"],
      excerpt: "| Terminal | Use |",
      tables: [
        {
          page: 14,
          rows: [
            ["Terminal", "Use"],
            ["F+", "Field positive"],
            ["A+", "Armature positive"],
          ],
        },
      ],
    }),
    source({
      unit_id: "44444444-4444-4444-8444-444444444444",
      rank: 4,
      citation_number: 4,
      document_id: WELDING,
      document_name: "tm-5-3431-201-10-welding-machine-scanned.pdf",
      pages: [3, 4],
      section: ["Operator controls"],
      excerpt: "Set the rheostat before starting the engine.",
      low_confidence_text: true,
    }),
    source({
      unit_id: "55555555-5555-4555-8555-555555555555",
      rank: 5,
      citation_number: 4,
      document_id: WELDING,
      document_name: "tm-5-3431-201-10-welding-machine-scanned.pdf",
      pages: [9],
      content_type: "figure",
      section: ["Operator controls"],
      excerpt: "Figure showing the control panel with switch S-12.",
      generated_description: true,
      unverified_identifiers: ["S-12", "R-4"],
    }),
    source({
      unit_id: "66666666-6666-4666-8666-666666666666",
      rank: 6,
      cited: false,
      citation_number: null,
      pages: [20],
      section: ["Magnetos"],
      excerpt: "Magneto timing is checked with a timing light.",
    }),
  ],
  primary_image: image({
    element_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    caption: "Figure 4-12. Shunt generator circuit",
  }),
  related_images: [
    image({
      element_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      page: 13,
      caption: null,
    }),
    image({
      element_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      page: 14,
      caption: "Figure 4-13. Terminal block",
    }),
  ],
};

/** An answered response whose text uses the full width, with no images. */
export const answerWithoutImages: AnswerBody = {
  ...answerWithFigures,
  not_covered: null,
  primary_image: null,
  related_images: [],
};
