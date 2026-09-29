import {
  CONVERSATION_KEY,
  loadConversation,
  saveConversation,
} from "@/conversation/persistence";
import { conversationReducer, emptyConversation, newTurn } from "@/conversation/state";

import { answerWithFigures } from "../../tests/fixtures/answers/sample";
import { fillSessionStorage } from "../../tests/storage";

function answeredConversation() {
  const turn = newTurn("How is a shunt generator wired?");
  const waiting = conversationReducer(emptyConversation, { type: "submitted", turn });
  return conversationReducer(waiting, {
    type: "answered",
    turnId: turn.id,
    response: answerWithFigures,
    requestId: "req-1",
  });
}

test("the conversation is written to sessionStorage and read back identically", () => {
  const conversation = answeredConversation();

  expect(saveConversation(conversation)).toBe("saved");

  expect(CONVERSATION_KEY).toBe("multimodal-rag.conversation.v1");
  expect(JSON.parse(sessionStorage.getItem(CONVERSATION_KEY)!)).toMatchObject({
    version: 1,
  });
  expect(loadConversation()).toEqual(conversation);
});

test("an empty tab starts with an empty conversation", () => {
  expect(loadConversation()).toEqual(emptyConversation);
});

test("a stored value with another version is discarded", () => {
  sessionStorage.setItem(CONVERSATION_KEY, JSON.stringify({ version: 2, turns: [] }));

  expect(loadConversation()).toEqual(emptyConversation);
});

test("a stored value that is not JSON is discarded", () => {
  sessionStorage.setItem(CONVERSATION_KEY, "{not json");

  expect(loadConversation()).toEqual(emptyConversation);
});

test("a full storage keeps the conversation in memory and says so", () => {
  fillSessionStorage();

  expect(saveConversation(answeredConversation())).toBe("quota_exceeded");
});

test("a turn that was waiting when the page reloaded comes back stopped", () => {
  const turn = newTurn("Interrupted question");
  saveConversation(conversationReducer(emptyConversation, { type: "submitted", turn }));

  const [restored] = loadConversation().turns;

  expect(restored).toMatchObject({
    id: turn.id,
    state: "stopped",
    stopReason: "reload",
  });
});

test("held turns keep their order after a reload", () => {
  let conversation = emptyConversation;
  for (const question of ["first", "second", "third"]) {
    conversation = conversationReducer(conversation, {
      type: "submitted",
      turn: newTurn(question),
    });
  }
  saveConversation(conversation);

  const restored = loadConversation().turns;

  expect(restored.map((turn) => [turn.question, turn.state])).toEqual([
    ["first", "stopped"],
    ["second", "held"],
    ["third", "held"],
  ]);
});
