"use strict";

function statusText(state) {
  return state && state.activeModel ? `$(hubot) ${state.activeModel}` : "$(hubot) Agent Hub";
}

module.exports = { statusText };
