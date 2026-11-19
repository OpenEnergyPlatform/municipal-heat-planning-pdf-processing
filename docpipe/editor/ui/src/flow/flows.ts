/* The drawings of the Flow tab besides the main flow: the chat's, and the flows of the follow-up passes, each by the
   name the tab gives it. The Prompts tab names a step's drawing with them too. */
import { t } from '../lib/i18n';

/* the chat's drawing (docpipe/editor/prompts.py CHAT_FLOW) */
export const CHAT = '#chat';
/* the flows of the follow-up passes in the order the plan of a run takes them */
export const PASS_ORDER = ['top_up', 'top_up_open', 'top_up_parameters', 'remap', 'recheck', 'review', 'start_at', 'example'];
/* the name of each flow of a follow-up pass, with the switch of the call that starts it */
export const passWord = (name: string): string => ({
  top_up: t('Read changed questions again (--top-up)'),
  top_up_open: t('Read the open places again (--top-up-open)'),
  top_up_parameters: t('Read further parameters (--top-up-parameters)'),
  remap: t('Map the lists again (--remap)'),
  recheck: t('Check the quotes again (--recheck)'),
  review: t('Second reading (--review)'),
  start_at: t('Start at the places found (--start-at)'),
  example: t('Example for a field (while a spec is compiled)'),
} as Record<string, string>)[name] || name;
/* the name of any drawing of the tab: the main flow, the chat's, a pass's */
export const flowWord = (which: string): string =>
  which === '' ? t('Main flow') : which === CHAT ? t('Chat: how a question is answered') : passWord(which);
