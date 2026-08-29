export function homePrompt(workspaceName) {
  if (workspaceName) {
    return {
      title: `我们应该在「${workspaceName}」中做些什么？`,
      subtitle: "描述目标，BlueWhale 会阅读项目、完成修改并运行验证。",
    };
  }
  return {
    title: "今天想做些什么？",
    subtitle: "从左侧打开一个项目，然后告诉 BlueWhale 你的目标。",
  };
}
