Workspace interaction study
===========================

Open [console.html](console.html) in a browser. It is a self-contained interaction sketch with no network requests, model calls, backend connection, or notification provider. Reloading or Reset clears the sample state. It is not an Android implementation or a model-behavior evaluation.

Static previews: [desktop](workspace-desktop.png) and [phone](workspace-phone.png).

The accepted UX decisions are: a coordinator conversation as the default for each task; direct access to all teammates; a persistent project team with separate task conversations; automatic brief task updates to the coordinator while complete direct conversations remain separate; and native Android access with push notifications and private connectivity first.

Try this sequence:

1. Open Android notifications in the coordinator conversation.
2. Choose `Discuss the notification with Maya`. Send the supplied example to see a visible shared update. Only this exact example triggers the scripted task-change behavior; arbitrary messages receive an explicit mock response.
3. Return to Coordinator. The task update and its impact appear without Maya's full conversation.
4. Leave an unsent draft, switch teammates and tasks, and return. Drafts stay attached to the original task/recipient during navigation.
5. Open Project team (Team on phone) to select either task conversation for the same teammate.
6. Preview notification, open its question, and respond. The attention count changes; reopening the notification shows the resolved state.
7. Use Phone or resize the browser to examine the same workflow at a narrow width.

Use this to discuss information hierarchy, context clarity, navigation effort, and attention handling. It does not establish model summary quality, authorization, durable delivery, device background behavior, or restart recovery. Those require the implementation and evaluation gates in [CONTROL_CONSOLE.md](../CONTROL_CONSOLE.md).

Still open: task creation and team sizing; autonomy and budget defaults; presentation of conflicting changes; project knowledge promotion; and the full review/acceptance flow. Styling is provisional. The interaction study should not freeze the native Android or TUI visual design.
