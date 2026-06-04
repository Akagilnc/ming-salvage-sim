const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("steam", {
  getStatus: () => ipcRenderer.invoke("steam:getStatus"),
  getAuthTicket: (identity) => ipcRenderer.invoke("steam:getAuthTicket", identity),
  cancelAuthTicket: (ticketId) => ipcRenderer.invoke("steam:cancelAuthTicket", ticketId),
  authenticateWithServer: (options) => ipcRenderer.invoke("steam:authenticateWithServer", options),
  addStatInt: (name, delta) => ipcRenderer.invoke("steam:addStatInt", name, delta),
  setStatInt: (name, value) => ipcRenderer.invoke("steam:setStatInt", name, value),
  flushStats: () => ipcRenderer.invoke("steam:flushStats"),
});
