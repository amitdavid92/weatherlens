/** Suggestion cards. `question` is exactly the prompt submitted (the original assignment questions). */
export const EXAMPLES = [
  { key: 'winter', title: 'Winter Exposure', question: 'Which hubs in the Midwest are most exposed to winter disruption?' },
  { key: 'compare', title: 'Compare Hubs', question: 'Compare Miami and Houston in terms of hurricane and flood exposure.' },
  { key: 'history', title: 'Historical Analysis', question: 'What percentage of days in Denver last year had snowfall?' },
  { key: 'drivers', title: 'Understand Risk Drivers', question: "Why is the Dallas hub's weather disruption risk high?" },
] as const

export const EXAMPLE_QUESTIONS: string[] = EXAMPLES.map((e) => e.question)
