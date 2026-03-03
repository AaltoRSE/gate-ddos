# Gate Distributed Document Oriented Solution

This is my attempt at making a way to generate answers in forms.  This
is just a first attempt focused on seeing if it works, and not a good
user interface.


My general plan:

- Create a system prompt describing your project.

- Run code with a template document:
  ```
  $ python3 gate-ddos.py SYSTEM_PROMPT.md DOCUMENT.docx -o DOCUMENT-new.docx
  ```
- In the document various things are tagged:
  ```markdown
  Gate document
  BEGIN-1
  ## Name of project
  ANSWER-1
  END-1

  BEGIN-2
  ## General description of the project
  ANSWER-2
  In several sententences, describe your project.
  END-2
  ```
  Everything between `BEGIN-x` and `END-x` is given to the LLM.  The
  output is placed between `ANSWER-x` and `END-x`.  The tags are
  stripped.  This allows you to maintain minimal divergence between
  upstream document templates and our code, while also avoiding the
  need for a more complex user interface.
