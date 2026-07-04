"""Prompt string constants used by SAGE agents.

Each template contains ``{placeholder}`` fields filled at runtime by builder
functions in :mod:`sage.agents`.

Mapping to paper Section 3 (Vulnerability Discovery Module):

* ``ATTACK_RELEVANT_SCHEMA`` — Perturbation Scope 3 (schema-relevant elements).
  Used by ``get_attack_prompt_used_description_problem``.
* ``ATTACK_IRRELEVANT_SCHEMA`` — Perturbation Scope 2 (schema-irrelevant
  elements). Used by ``get_attack_prompt_unused_description_problem``.
* ``ATTACK_QUESTION`` — Perturbation Scope 1 (natural language queries).
  Used by ``get_attack_prompt_question_problem``.

Codex Evolution & Management Module:

* ``JUDGE_ANALYZE_ERROR`` — Step 6, Summarizer error analysis.
* ``JUDGE_SUMMARIZE_ERROR`` — Step 6, structured error taxonomy.
* ``SUMMARIZE_STRATEGY`` — Step 7, semantic compression of strategy entries.

The default-fallback bullet list used when the Vulnerability Codex returns no
relevant strategies (cold start) is kept as ``DEFAULT_ATTACK_STRATEGY_FALLBACK``.
"""

from __future__ import annotations

# ----------------------------------------------------------------------
# Cold-start fallback when StrategyLib returns no relevant entries.
# ----------------------------------------------------------------------

DEFAULT_ATTACK_STRATEGY_FALLBACK = """
    1.	Synonym Substitution
	•	Replace verbs, nouns, or adjectives with synonyms.
	•	Example: “highest” → “maximum”, “list” → “show”
	•	Goal: Evaluate whether the model handles semantic equivalence across different words.
	2.	Entity Renaming with Clarifier
	•	Replace table or column names with natural language descriptions.
	•	Example: “flight code” → “identifier for a flight”
	•	Goal: Test if the model is overly dependent on exact schema tokens instead of semantic meaning.
	3.	Column Hiding
	•	Omit minor details or columns not essential to query intent.
	•	Example: “show all employees” without mentioning fields like email or age.
	•	Goal: Check if the model requires unnecessary context to answer correctly.
	4.	Question Simplification
	•	Compress verbose questions into concise expressions of the same intent.
	•	Example: “Which departments have employees who joined after 2020?” → “Departments with employees joining post-2020?”
	•	Goal: Evaluate if the model understands reduced, minimal forms of the query.
	5.	Passive-to-Active Transformation
	•	Change voice without altering meaning.
	•	Example: “Which books were written by Shakespeare?” → “Which books did Shakespeare write?”
	•	Goal: Test the model’s ability to generalize across syntactic structures.
	6.	Interrogative Variation
	•	Change how the question is asked without changing intent.
	•	Example: “What is the total sales?” → “Could you tell me the total sales?”
	•	Goal: Evaluate robustness to natural question variations.
	7.	Column Mention Order Shuffling
	•	Change the order of columns/entities mentioned in natural language.
	•	Example: “List student names and IDs” → “Show IDs and names of students”
	•	Goal: Determine if the model is rigidly dependent on mention order.
	8.	Negation Rewording (Careful Use)
	•	Modify or reverse negation without changing intent (use with caution).
	•	Example: “Employees who are not managers” → “All non-manager employees”
	•	Goal: Check whether the model correctly parses logical negation.
	9.	Numeric Generalization
	•	Replace specific numbers with quantifiers or descriptors.
	•	Example: “more than 5 orders” → “more than a few orders”
	•	Goal: Stress-test how the model handles approximate quantities or vague numeric language.
	10.	Add Irrelevant Clauses
	•	Add non-essential information that does not alter the query outcome.
	•	Example: “Show all orders, sorted by date if available.” (even if no such column exists)
	•	Goal: Test model sensitivity to irrelevant or redundant phrasing.
    """


# ----------------------------------------------------------------------
# Attack prompts — three perturbation scopes (paper Section 3.2.1)
# ----------------------------------------------------------------------

ATTACK_RELEVANT_SCHEMA = """
    You are an expert in prompt-based robustness evaluation for database-related tasks.
    ### Task:
    Please **modify the database-related information** while ensuring that the **core semantics and the correct answer remain unchanged**. Your goal is to introduce **greater lexical, structural, and semantic diversity** to challenge the robustness of the model.
    You may revise the following elements for each column:
    - `column_description`: Modify the description using paraphrasing, synonyms, different sentence structures, or multilingual expressions.
    - `value_description`: Alter the value type description or re-express the value mappings, ranges, or classifications.
    - `example_value`: Enrich the example values with varied, realistic, and semantically appropriate entries.
    **Important:**
    - Do **not** change the table name or column name.
    - Your output must be in **strict JSON format** as shown below.
    - You must change the metadata for **at least 3 columns** and **at most 5 columns**.
    Here are some output Examples:
    # Example 1:
    ```json
    {{
      "students": [
        {{
          "column": "age",
          "improvement": "Rephrased the column description using a more technical tone, updated value type with synonyms, and added diverse numerical examples.",
          "column_description": "Numerical age of each enrolled student, expressed in full years.",
          "value_description": "Integer type; represents the student's age in years (e.g., 18-30).",
          "example_value": ["19", "22", "25"]
        }}
      ]
    }}
    ```
     # Example 2:
     ```json
    {{
      "courses": [
        {{
          "column": "course_name",
          "improvement": "Used multilingual expression and added more specific context to the description; diversified course names.",
          "column_description": "名称 / Name of the academic course offered in the semester.",
          "value_description": "Textual labels representing the full name of each course.",
          "example_value": ["Data Structures", "计算机网络", "Machine Learning"]
        }}
      ]
    }}
     ```
     # Example 3:
     ```json
     {{
      "departments": [
        {{
          "column": "department_id",
          "improvement": "Clarified the ID purpose, reworded the value range with classification-based description, and gave representative ID values.",
          "column_description": "Unique identifier assigned to each department unit.",
          "value_description": "Positive integer in the range 100–999; denotes department code (e.g., 101 = Math, 202 = History).",
          "example_value": ["101", "202"]
        }}
      ]
    }}
     ```
Now it is your turn to summarize
    Below is a partial view of the database schema. It includes only the tables and columns that are relevant to answering the given question; unrelated schema elements have been omitted.
    {json_str}
    Question: {question}
    Evidence: {evidence}
    The gold SQL query is: {gold_sql}

    Return your modifications using the following structure:
    ```json
    {{
      "table_name": [
        {{
          "column": "column_name",
          "improvement": "Describe your strategy for modifying this column's metadata.",
          "column_description": "Modified description of the column.",
          "value_description": "Modified description of the values.",
          "example_value": ["example1", "example2"]
        }}
      ]
    }}
    ```
     Here are some successful attack strategies you can refer to.{error_strategies}
     #The column_description and value_description fields should each be no longer than 100 tokens.
     Now it’s your turn. Please return your answer strictly in the above JSON format.
            """


ATTACK_IRRELEVANT_SCHEMA = """
---
### Task:

Your task is to **modify the provided database-related information** while ensuring that the **core semantics and the correct answer remain unchanged**.

Your goal is to introduce **maximum lexical, structural, and semantic diversity** in order to **evaluate the model's robustness** against variations in metadata.
You are allowed to revise the following fields for each column:
- **`column_description`**: Modify the column description using paraphrasing, synonyms, different sentence structures, or even multilingual expressions (e.g., English + Chinese).
- **`value_description`**: Change the way value types, ranges, or categories are described. This may involve unit shifts, re-categorization, or rewording of type information.
- **`example_value`**: Add more diverse, realistic, or representative sample values while ensuring consistency with the field’s meaning.
---
### ⚠️ Important Guidelines:
- **Do not** change the table names or column names.
- **Do not** alter the underlying meaning or change the final answer.
- You must output your result in the **strict JSON format** shown below.
- You must change the metadata for **at least 3 columns** and **at most 5 columns**.
---
### Output Format:
```json
{{
  "table_name": [
    {{
      "column": "column_name",
      "improvement": "Describe your strategy for modifying this column's metadata.",
      "column_description": "Modified description of the column.",
      "value_description": "Modified description of the values.",
      "example_value": ["example1", "example2"]
    }}
  ]
}}
# Example 1:
```json
{{
  "employees": [
    {{
      "column": "salary",
      "improvement": "Adjusted the description to use financial terminology and alternative unit expression (monthly vs annual); diversified numerical range with realistic salary samples.",
      "column_description": "Monthly base compensation (in USD) provided to each employee, before deductions.",
      "value_description": "Floating-point number; typically ranges from 3000.00 to 12000.00 depending on role and seniority.",
      "example_value": ["3500.00", "8200.50"]
    }}
  ]
}}
```
# Example 2:
```json
{{
  "products": [
    {{
      "column": "category",
      "improvement": "Rephrased the category description using domain-specific language, included multilingual labeling to increase lexical diversity.",
      "column_description": "产品分类 / Product category label assigned for inventory grouping and filtering.",
      "value_description": "String type; includes groupings such as electronics, furniture, apparel, etc.",
      "example_value": ["电子产品", "Home Appliances"]
    }}
  ]
}}
```
# Example 3:
```json
{{
  "books": [
    {{
      "column": "title",
      "improvement": "Enriched the description by referencing publishing context; introduced titles with stylistic and linguistic variation.",
      "column_description": "Official title printed on the book’s cover or recorded in the publisher’s registry.",
      "value_description": "Free-text string; typically composed of alphanumeric words with potential punctuation.",
      "example_value": ["The Silent Patient", "孤独小说家"]
    }}
  ]
}}

Below is a partial view of the database schema. It includes only the tables and columns that are directly relevant to answering the given question; all unrelated schema elements have been omitted.
{json_str}
Question: {question}
Evidence: {evidence}
The gold SQL query is: {gold_sql}
Here are some successful attack strategies you can refer to.{error_strategies}
#The column_description and value_description fields should each be no longer than 100 tokens.
Now it’s your turn. Please return your answer strictly in the above JSON format.
```
                    """


ATTACK_QUESTION = """
---
### Task:
Please **rewrite the question and the evidence** in a way that **preserves the original intent and does not change the final correct answer** (i.e., the gold SQL query must still be valid and applicable).
Your rewritten version should:
- Better reflect **real-world use cases or natural user phrasing**.
- Increase **linguistic and structural diversity** (e.g., use indirect expressions, varied syntax, colloquial or formal tone, etc.).
- Introduce **more contextual framing, ambiguity, or reasoning cues** to evaluate the model’s robustness.
- Remain **faithful to the original semantics and answer**.
---
### Guidelines:
- Do **not** change the final answer (i.e., gold SQL must still be valid).
- Focus on **rewriting**, not expanding or omitting information.
- You must **describe your modification strategy** clearly in the `improvement` field.
---
### Output Format:
Please return your output strictly in the following JSON format:
```json
{{
  "improvement": "Describe what changes you made and why (e.g., added contextual realism, rephrased with ambiguity, used colloquial style, etc.)",
  "question": "your rewritten question",
  "evidence": "your rewritten evidence"
}}
# Example 1:
```json
{{
  "improvement": "Rephrased the question to use more natural, informal language ('doing the best, salary-wise'), and added soft ambiguity in the evidence by clarifying the intent with a real-world qualifier (excluding bonuses).",
  "question": "Can you tell me which employees have been doing the best, salary-wise?",
  "evidence": "I'm referring to those earning the highest base pay — not including bonuses or commissions."
}}
# Example 2:
```json
{{
  "improvement": "Embedded the question in a realistic scenario (reviewing staff directory), and framed it as an indirect query. The evidence also uses synonyms ('managing multiple divisions') to increase lexical diversity.",
  "question": "I’m reviewing our staff directory — who among the team leads more than one department?",
  "evidence": "Check if any staff member is listed as managing multiple divisions simultaneously."
}}
```
# Example 3:
```json
{{
  "improvement": "Transformed the question into a two-step dialogue-style query, simulating multi-turn reasoning. Evidence rephrased with emphasis on action ('appears most frequently'), introducing potential ambiguity to test deeper understanding.",
  "question": "We already know how many courses each student is enrolled in. What I want to find out now is: which student has taken the most?",
  "evidence": "Look at the enrollment records and determine which student appears most frequently across different course entries."
}}
```
Now it is your turn:
Below is the database schema:
{schema}
Question: {question}
Evidence: {evidence}
The gold SQL query is: {gold_sql}
Here are some successful attack strategies you can refer to.{error_strategies}
return your rewritten content in the format above.
                    """


# ----------------------------------------------------------------------
# Codex Evolution prompts (Section 3.3)
# ----------------------------------------------------------------------

JUDGE_ANALYZE_ERROR = """---
Example 1:

Original Input (before modification):
User Question: Which course has more than 2 credits?

Modified Input (after perturbation):
User Question: Which course has more than 3 credits?

Gold SQL:
SELECT name FROM Courses WHERE credits > 3

Model’s Predicted SQL:
SELECT name FROM Courses WHERE credits > 2

Analysis:
- Error diagnosis:
  The model incorrectly retained the original condition `credits > 2` instead of updating it to `credits > 3`, failing to reflect the revised threshold in the user's question.
- Trigger identification:
  The subtle scalar shift from "2 credits" to "3 credits" in the question was overlooked. The rest of the sentence remained unchanged, which likely caused the model to anchor on the original number.
- General pattern:
  This demonstrates that the model is vulnerable to small scalar perturbations, especially when sentence structure and semantics remain constant. Such numeric edits are a lightweight yet effective way to trigger semantic errors without altering surface structure.

---

Example 2:

Original Input (before modification):
Contextual Evidence: The HR department typically offers high salaries.
User Question: List all employees in the HR department who earn more than 5000.

Modified Input (after perturbation):
Contextual Evidence: The Finance department typically offers high salaries.
User Question: List all employees in the HR department who earn more than 5000.

Gold SQL:
SELECT name FROM Employees WHERE department = 'HR' AND salary > 5000

Model’s Predicted SQL:
SELECT name FROM Employees WHERE department = 'Finance' AND salary > 5000

Analysis:
- Error diagnosis:
  The model selected `'Finance'` as the department in the SQL query, contradicting the user's explicit reference to `'HR'`.
- Trigger identification:
  The contextual evidence was adversarially modified to mention the "Finance department" as associated with high salaries. This misled the model into prioritizing the supporting context over the user question.
- General pattern:
  The model overweights background context, even when it conflicts with explicit user intent. This indicates a susceptibility to **evidence priming**, where injected bias in supporting sentences can override direct instructions.

Now it is your turn.

Below is the current evaluation case:

Original Input (before modification):
`{data_changed_before}`

Modified Input (after perturbation):
`{data_changed_after}`

Gold SQL (expected correct query):
```sql
{gold_sql}
```

Model’s Predicted SQL and thought:
{target_answer_reason}


Please provide a detailed analysis that includes:
- **Error diagnosis**: What exactly did the model get wrong, and how?
- **Trigger identification**: Which changes likely caused the failure, and why?
- **General pattern**: What does this reveal about the model’s behavior, and how might similar strategies be used to provoke errors?
                        """


JUDGE_SUMMARIZE_ERROR = """
### Your Tasks:
1. **Extract and enumerate all distinct errors** the model made, based on the analysis.
2. For each error:
    - Assign an **errorType** from the following options:
      {error_type_json}
    - Assign a **toleranceLevel** from the following:
      {error_tolerance}
    - Provide:
      - `errorDetail`: a **detailed description** of what caused the error and how it manifested.
      - `errorSummary`: a **concise abstraction** that can be used for future similarity-based matching. This should focus on the core failure pattern.
3. Return the result in **exactly** the following JSON format (as a Python list of dictionaries):
```json
[
  {{
    "errorStrategies": {{
      "errorDetail": "...",
      "errorType": "...",
      "errorSummary": "..."
    }},
    "toleranceLevel": "..."
  }},
  ...
]
```
Constraints:
	•	There may be multiple errors in the same case, so analyze and report each separately.
	•	errorType should be one of the keys from error_type_json
	•	toleranceLevel should be one of the keys from error_tolerance
	•	Be accurate, precise, and avoid repetition.
	•	when errorType is OTHER,you must give your analysis and errorDetail and errorSummary

Here are some examples:
Example 1:
model's reasoning/thoughts:
The model rewrote the SQL using a LEFT JOIN instead of an INNER JOIN, but the join condition ensures equivalent filtering. It also selected column aliases in a different order, which does not impact the result. The model’s SQL yields the same records as the gold query.
output:
```json
[
  {{
    "errorStrategies": {{
      "errorDetail": "Although the model replaced INNER JOIN with LEFT JOIN, the condition in the WHERE clause ensured the result set was unaffected. Also, column aliases were renamed, but the semantics remained the same.",
      "errorType": "OTHER",
      "errorSummary": "Structural or alias-level changes that preserve result semantics"
    }},
    "toleranceLevel": "Equivalent_Answer"
  }}
]
```
Example 2:
model's reasoning/thoughts:
The modified input removed the mention of a specific filtering condition on enrollment year, which was present in the original question. The model did not include this condition in the SQL query as a result. This is not due to model error, but due to insufficient information provided in the revised prompt.
output:
```json
[
  {{
    "errorStrategies": {{
      "errorDetail": "The adversarial modification removed the reference to a specific enrollment year, so the model did not filter the results accordingly. This is due to loss of base information rather than model reasoning error.",
      "errorType": "QUESTION_INTERPRETATION_ERROR",
      "errorSummary": "Loss of filtering condition due to missing contextual detail"
    }},
    "toleranceLevel": "BASE_INFO_ERROR"
  }}
]
```
Example 3:
model's reasoning/thoughts:
The model misinterpreted the group-by condition, aggregating on the wrong column (department_id instead of course_id), and incorrectly used COUNT instead of AVG. It also missed the filtering condition on year = 2022, even though that constraint remained present in the modified prompt.
output:
```json
[
  {{
    "errorStrategies": {{
      "errorDetail": "The model misinterpreted the aggregation logic, grouping by 'department_id' rather than the required 'course_id'. This leads to a different granularity of results.",
      "errorType": "AGGREGATION_ERROR",
      "errorSummary": "Incorrect grouping logic alters query semantics"
    }},
    "toleranceLevel": "Answer_Error"
  }},
  {{
    "errorStrategies": {{
      "errorDetail": "The model used COUNT instead of AVG, which completely changes the statistical meaning of the query output.",
      "errorType": "AGGREGATION_FUNCTION_MISUSE",
      "errorSummary": "Wrong aggregate function changes result intention"
    }},
    "toleranceLevel": "Answer_Error"
  }},
  {{
    "errorStrategies": {{
      "errorDetail": "The model omitted the filter condition 'year = 2022', which remained in the prompt. This causes the answer to include unintended records.",
      "errorType": "CONDITION_OMISSION",
      "errorSummary": "Model failed to preserve an explicit filtering constraint"
    }},
    "toleranceLevel": "Answer_Error"
  }},
    {{
    "errorStrategies": {{
      "errorDetail": "The model produced an SQL query that superficially matched the prompt but added unnecessary table joins and subqueries. These structural changes were not justified by the question and made the query logically harder to interpret or debug. This type of error doesn't fall into syntax, semantic or typical constraint mistakes but reflects general overengineering.",
      "errorType": "OTHER",
      "errorSummary": "Overcomplicated query structure without justification"
    }},
    "toleranceLevel": "Answer_Error"
  }}
]
```
Now it is your turn:
Here is the error analysis (model's reasoning/thoughts):
{error_analysis}
give me the output
                        """


SUMMARIZE_STRATEGY = """
You are provided with a group of similar error strategies that were observed during robustness testing of a large language model (LLM) for text-to-SQL generation.

These strategies stem from adversarially modified prompts that were used to probe the model's weaknesses.
The goal is to **deduplicate and refine** these examples by either:
•	Group and compress strategies that share a common failure pattern, such as misunderstanding vague phrasing, procedural confusion, or structural misalignment.
•	Summarize the shared failure mechanism clearly in errorDetail and errorSummary.
•	Keep a representative concrete example using for example to illustrate the pattern.
•	If strategies differ substantially (e.g., different semantic confusions or attack techniques), do not merge — return them as separate entries.
You should only modify the following fields:
•	errorStrategies.errorDetail: Describe the shared failure type and mechanism, followed by a concrete example (e.g., “For example, the model was asked to ‘rank the districts’ instead of ‘select the best one’, which led to a sorting query rather than a top-1 selection.”).
•	errorStrategies.errorSummary: Condense the failure pattern into a short, generalizable form.
•	Keep errorType and toleranceLevel unchanged.

Please return your answer as a Python list of dictionaries in the exact format below:

```json
[
  {{
    "errorStrategies": {{
      "errorDetail": "...",
      "errorType": "...",
      "errorSummary": "..."
    }},
    "toleranceLevel": "..."
  }},
  ...
]
```
---

##Example Input (4 similar strategies):
```json
[
  {{
    "errorStrategies": {{
      "errorDetail": "The model returned a placeholder (`Code-73`) instead of a valid SQL query, indicating a complete failure to understand the user's intent or construct the required query logic. It did not perform the necessary table joins, filtering, grouping, or ordering to answer the question.",
      "errorType": "QUESTION_INTERPRETATION_ERROR",
      "errorSummary": "Model failed to interpret the question intent and construct a valid SQL query"
    }},
    "toleranceLevel": "Answer_Error"
  }},
  {{
    "errorStrategies": {{
      "errorDetail": "The adversarial modification rephrased the question from a direct factual query ('highest average score') to a more ambiguous and subjective one ('performing best'), which confused the model into not generating a proper SQL query.",
      "errorType": "QUESTION_INTERPRETATION_ERROR",
      "errorSummary": "Ambiguous or subjective phrasing disrupts model's intent recognition"
    }},
    "toleranceLevel": "BASE_INFO_ERROR"
  }},
  {{
    "errorStrategies": {{
      "errorDetail": "The modified evidence introduced a comparative and procedural framing ('sort the districts by their average Reading scores'), which shifted the model's focus from selecting the top result to a different task structure, leading to a breakdown in the correct SQL formulation.",
      "errorType": "QUESTION_INTERPRETATION_ERROR",
      "errorSummary": "Reframing the task as sorting instead of selecting maximum causes query deviation"
    }},
    "toleranceLevel": "BASE_INFO_ERROR"
  }},
  {{
    "errorStrategies": {{
      "errorDetail": "The model failed to recognize that 'performing best' in the context of Reading scores should be interpreted as selecting the district with the highest average Reading score, which requires using `ORDER BY` with `LIMIT 1`, or an equivalent aggregation strategy.",
      "errorType": "COLUMN_SEMANTICS_ERROR",
      "errorSummary": "Misinterpretation of 'performing best' as requiring sorting instead of maximum selection"
    }},
    "toleranceLevel": "Answer_Error"
  }}
]
```
# Compressed Output:
```json
[
  {{
    "errorStrategies": {{
      "errorDetail": "The model struggles to interpret vague or subjective phrasing that departs from precise factual queries, leading to incorrect or failed SQL generation. This includes both total breakdowns (e.g., returning a placeholder like `Code-73`) and incorrect logic when terms like 'performing best' are used. For example, when asked 'Which district is performing best in Reading?', the model failed to translate it into a `ORDER BY avg(Reading) LIMIT 1` structure, or returned an empty placeholder instead of a valid SQL query.",
      "errorType": "QUESTION_INTERPRETATION_ERROR",
      "errorSummary": "Vague or subjective phrasing leads to misinterpretation or complete failure to generate valid SQL"
    }},
    "toleranceLevel": "Answer_Error"
  }},
  {{
    "errorStrategies": {{
      "errorDetail": "When adversarial modifications reframe a selection task into a comparative or procedural one (e.g., from 'Which district performs best' to 'Sort the districts by average Reading scores'), the model loses the original intent and produces a query structure aligned with the rephrased instruction. For example, it may generate a full sorting query instead of selecting only the top item, deviating from the intended output.",
      "errorType": "QUESTION_INTERPRETATION_ERROR",
      "errorSummary": "Procedural reframing shifts model focus from selection to sorting"
    }},
    "toleranceLevel": "BASE_INFO_ERROR"
  }}
]
```
By compressing similar errors into representative ones, we:
	•	Remove redundancy in strategy sets.
	•	Improve clarity of model failure cases.
	•	Highlight specific failure patterns tied to attack types, enabling better fine-tuning or filtering
	{max_size}
Now compress the following set of error strategies if needed:
```json
{error_analysis}
```
      """
