// Home Assistant core's .prettierrc.js, with `homeassistant/` read as `custom_components/`
// and core's brands glob dropped. Copy verbatim. JSON keys are sorted, and a manifest keeps
// domain and name first.

/** @type {import("prettier").Config} */
module.exports = {
  overrides: [
    {
      files: "./custom_components/**/*.json",
      options: {
        plugins: [require.resolve("prettier-plugin-sort-json")],
        jsonRecursiveSort: true,
        jsonSortOrder: JSON.stringify({ [/.*/]: "numeric" }),
      },
    },
    {
      files: ["manifest.json"],
      options: {
        // domain and name should stay at the top
        jsonSortOrder: JSON.stringify({
          domain: null,
          name: null,
          [/.*/]: "numeric",
        }),
      },
    },
  ],
};
