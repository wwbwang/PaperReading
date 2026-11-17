// An anonymous reviewer can publish multiple distinct official review notes.
// Never choose one by position, rating or timestamp, or infer a missing alias.
export function notesForReviewer(notes, alias) {
  return alias ? notes.filter(note => note.reviewer === alias) : [];
}

export function additionalReviewerAliases(scores, notes) {
  const existing = new Set(scores.map(review => review.reviewer));
  return [...new Set(notes.map(note => note.reviewer).filter(alias => alias && !existing.has(alias)))];
}
