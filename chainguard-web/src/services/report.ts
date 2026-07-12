export async function getExecutiveReport() {
  return { netBenefit: 732000, riskCount: 18, avgResponseHours: 5.2 };
}

export async function getOperationReport() {
  return { funnel: [18, 8, 5, 4, 3], overdueRate: 0.08 };
}

export async function getResponseReport() {
  return { events: [{ id: 'inc-supplier-shutdown', title: '苏州芯片封测厂停产', responseHours: 9.5, costDiff: -22000 }] };
}
