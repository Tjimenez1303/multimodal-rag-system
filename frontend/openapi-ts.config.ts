import { defineConfig } from "@hey-api/openapi-ts";

// Plugins are declared explicitly rather than relying on the default list.
export default defineConfig({
  input: "./openapi.json",
  output: {
    path: "./src/client",
    // Generated code is not written for exactOptionalPropertyTypes, so it is not
    // type-checked, like library declarations under skipLibCheck.
    header: ({ defaultValue }) => ["// @ts-nocheck", ...defaultValue],
  },
  plugins: [
    "@hey-api/client-fetch",
    "@hey-api/typescript",
    "zod",
    { name: "@hey-api/sdk", validator: { request: false, response: "zod" } },
  ],
});
