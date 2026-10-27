import { defineConfig } from "orval";

export default defineConfig({
  windiq: {
    input: `${process.env.BACKEND_URL ?? "http://localhost:8000"}/api/openapi.json`,
    output: {
      target: "src/api/generated",
      client: "react-query",
      httpClient: "fetch",
      mode: "split",
      clean: true,
      override: {
        mutator: { path: "./src/api/fetcher.ts", name: "customFetch" },
        fetch: {
          // return the payload directly instead of a {data, status} envelope
          includeHttpResponseReturnType: false,
        },
      },
    },
  },
});
