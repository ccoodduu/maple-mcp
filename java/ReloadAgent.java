import java.io.*;
import java.lang.instrument.Instrumentation;
import java.net.ServerSocket;
import java.net.Socket;

public class ReloadAgent {
    private static volatile boolean running = false;
    private static final int PORT = 19876;
    private static File logFile;

    public static void premain(String args, Instrumentation inst) { init(); }
    public static void agentmain(String args, Instrumentation inst) { init(); }

    private static void log(String msg) {
        try (PrintWriter w = new PrintWriter(new FileWriter(logFile, true))) {
            w.println("[ReloadAgent] " + msg);
        } catch (Exception e) {}
    }

    private static void init() {
        logFile = new File(System.getProperty("user.home") + "/maple_agent.log");
        log("init at " + new java.util.Date());
        if (running) { log("already running"); return; }
        running = true;

        Thread t = new Thread(() -> {
            try (ServerSocket server = new ServerSocket(PORT)) {
                log("listening on port " + PORT);
                while (running) {
                    try (Socket client = server.accept();
                         BufferedReader in = new BufferedReader(new InputStreamReader(client.getInputStream()));
                         PrintWriter out = new PrintWriter(client.getOutputStream(), true)) {
                        String cmd = in.readLine();
                        if ("ping".equals(cmd)) {
                            out.println("pong");
                        } else if (cmd != null && cmd.startsWith("reload ")) {
                            out.println(reload(cmd.substring(7).trim()));
                        } else if ("save".equals(cmd)) {
                            out.println(save());
                        } else if (cmd != null && cmd.startsWith("export ")) {
                            out.println(exportPdf(cmd.substring(7).trim()));
                        } else if ("evalnew".equals(cmd)) {
                            out.println(evalNew());
                        } else if (cmd != null && cmd.startsWith("open ")) {
                            out.println(open(cmd.substring(5).trim()));
                        } else if ("getpath".equals(cmd)) {
                            out.println(getOpenPath());
                        } else {
                            out.println("unknown: " + cmd);
                        }
                    } catch (Exception e) {
                        log("client error: " + e.getMessage());
                    }
                }
            } catch (Exception e) {
                log("server error: " + e.getMessage());
            }
        }, "ReloadAgent");
        t.setDaemon(true);
        t.start();
    }

    private static Object getManager() throws Exception {
        Class<?> wmiClass = Class.forName("com.maplesoft.worksheet.application.WmiWorksheet");
        Object instance = wmiClass.getMethod("getInstance").invoke(null);
        return instance.getClass().getMethod("getWorksheetManager").invoke(instance);
    }

    private static Object getActiveWindow() throws Exception {
        Object mgr = getManager();
        return mgr.getClass().getMethod("getActiveWindow").invoke(mgr);
    }

    private static String save() {
        log("save requested");
        try {
            final Object wnd = getActiveWindow();
            if (wnd == null) return "error: no active window";

            final String[] result = {"pending"};
            javax.swing.SwingUtilities.invokeAndWait(() -> {
                try {
                    boolean saved = (boolean) wnd.getClass()
                        .getMethod("saveWindowContents").invoke(wnd);
                    result[0] = saved ? "ok" : "error: save returned false";
                    log("save: " + result[0]);
                } catch (Exception e) {
                    log("save EDT error: " + e.getMessage());
                    result[0] = "error: " + e.getMessage();
                }
            });
            return result[0];
        } catch (Exception e) {
            log("save error: " + e.getMessage());
            return "error: " + e.getMessage();
        }
    }

    // Render a .mw to PDF via Maple's export pipeline, running INSIDE the live
    // GUI JVM. Unlike a standalone export JVM, this process already has a screen
    // device (acquired at GUI startup), so it still works when the screen is
    // locked. Arg is "INPATH|OUTPATH" ('|' is illegal in Windows paths).
    private static String exportPdf(String arg) {
        int bar = arg.lastIndexOf('|');
        if (bar < 0) return "error: bad args (expected IN|OUT)";
        String in = arg.substring(0, bar);
        String out = arg.substring(bar + 1);
        log("export requested: " + in + " -> " + out);
        try {
            Class<?> util = Class.forName(
                "com.maplesoft.worksheet.util.WmiWorksheetExportUtils");
            util.getMethod("exportPDF", String.class, String.class)
                .invoke(null, in, out);
            java.io.File f = new java.io.File(out);
            if (f.exists() && f.length() > 0) {
                log("export ok: " + f.length() + " bytes");
                return "ok";
            }
            return "error: empty output";
        } catch (Throwable t) {
            log("export error: " + t);
            return "error: " + t;
        }
    }

    // Execute ONLY the executable groups that have no output yet (i.e. the ones
    // just written by the MCP). Existing/manually-edited results keep their
    // output and are left untouched. Mirrors Maple's "Execute Worksheet" command
    // (WmiExecutionVisitor + WmiExecuteGroups) but filters to getOutput()==null.
    private static String evalNew() {
        log("evalnew requested");
        try {
            final Object wnd = getActiveWindow();
            if (wnd == null) return "error: no active window";
            Object view = wnd.getClass().getMethod("getWorksheetView").invoke(wnd);
            if (view == null) return "error: no view";
            final Object model = view.getClass().getMethod("getModel").invoke(view);

            Class<?> wmiModel = Class.forName("com.maplesoft.mathdoc.model.WmiModel");
            Class<?> lock = Class.forName("com.maplesoft.mathdoc.model.WmiModelLock");
            java.util.List<Object> todo = new java.util.ArrayList<>();

            lock.getMethod("writeLock", wmiModel, boolean.class).invoke(null, model, true);
            try {
                Class<?> visitorC = Class.forName(
                    "com.maplesoft.worksheet.controller.WmiExecutionVisitor");
                Object visitor = visitorC.getDeclaredConstructor().newInstance();
                Class<?> searcher = Class.forName("com.maplesoft.mathdoc.model.WmiModelSearcher");
                Class<?> svisitor = Class.forName("com.maplesoft.util.WmiSearchVisitor");
                searcher.getMethod("visitDepthFirst", wmiModel, svisitor)
                    .invoke(null, model, visitor);
                java.util.List<?> all = (java.util.List<?>)
                    visitorC.getMethod("getExecutionGroups").invoke(visitor);
                for (Object g : all) {
                    Object out = g.getClass().getMethod("getOutput").invoke(g);
                    boolean canExec = (boolean) g.getClass().getMethod("canExecute").invoke(g);
                    if (out == null && canExec) todo.add(g);
                }
            } finally {
                lock.getMethod("writeUnlock", wmiModel).invoke(null, model);
            }
            log("evalnew: " + todo.size() + " unevaluated group(s)");
            if (todo.isEmpty()) return "ok: 0";

            Class<?> execC = Class.forName(
                "com.maplesoft.worksheet.controller.edit.WmiExecuteGroups");
            Object exec = execC.getConstructor(java.util.List.class).newInstance(todo);
            execC.getMethod("start").invoke(exec);

            // Wait for the kernel to finish (poll isAnythingExecutingInDocument).
            Object doc = wmiModel.getMethod("getDocument").invoke(model);
            Class<?> egm = Class.forName("com.maplesoft.worksheet.model.WmiExecutionGroupModel");
            Class<?> mdm = Class.forName("com.maplesoft.mathdoc.model.WmiMathDocumentModel");
            java.lang.reflect.Method isExec =
                egm.getMethod("isAnythingExecutingInDocument", mdm);
            Thread.sleep(400);
            for (int i = 0; i < 900; i++) {  // up to ~90s
                if (!((boolean) isExec.invoke(null, doc))) break;
                Thread.sleep(100);
            }

            final String[] result = {"ok: " + todo.size()};
            javax.swing.SwingUtilities.invokeAndWait(() -> {
                try { wnd.getClass().getMethod("saveWindowContents").invoke(wnd); }
                catch (Exception e) { log("evalnew save error: " + e.getMessage()); }
            });
            log("evalnew complete: " + result[0]);
            return result[0];
        } catch (Throwable t) {
            log("evalnew error: " + t);
            if (t.getCause() != null) log("  cause: " + t.getCause());
            return "error: " + t;
        }
    }

    // Open a .mw in Maple the same way File > Open does once its chooser has
    // returned a file: WmiWorksheetFileOpen.loadAFile does the whole job —
    // new tab/window, styles, backward-compat check, and (unlike loadContents)
    // it sets the view's file path, so getpath/save/reload work on the result.
    // It is protected, hence setAccessible.
    private static String open(String filePath) {
        log("open requested: " + filePath);
        try {
            final java.io.File file = new java.io.File(filePath);
            if (!file.isFile()) return "error: no such file: " + filePath;

            // Reopening an open file would give it a second tab, so treat an
            // already-open document as success and leave it alone.
            Object mgr = getManager();
            if (mgr != null) {
                Object already = mgr.getClass()
                    .getMethod("isFileOpen", String.class).invoke(mgr, filePath);
                if (Boolean.TRUE.equals(already)) {
                    log("already open");
                    return "ok";
                }
            }

            Class<?> openCls = Class.forName(
                "com.maplesoft.worksheet.controller.file.WmiWorksheetFileOpen");
            Class<?> docViewCls = Class.forName(
                "com.maplesoft.mathdoc.view.WmiMathDocumentView");
            final java.lang.reflect.Method loadAFile =
                openCls.getDeclaredMethod("loadAFile", java.io.File.class, docViewCls);
            loadAFile.setAccessible(true);

            // Context view for the open. Null is acceptable — Maple then opens
            // in a new window rather than beside an existing one.
            Object ctx = null;
            try {
                Object wnd = getActiveWindow();
                if (wnd != null) {
                    ctx = wnd.getClass().getMethod("getWorksheetView").invoke(wnd);
                }
            } catch (Exception ignored) {
                log("no context view, opening standalone");
            }

            final Object fCtx = ctx;
            final String[] result = {"pending"};
            javax.swing.SwingUtilities.invokeAndWait(() -> {
                try {
                    loadAFile.invoke(null, file, fCtx);
                    result[0] = "ok";
                    log("open complete");
                } catch (Exception e) {
                    Throwable c = e.getCause() != null ? e.getCause() : e;
                    log("open EDT error: " + c);
                    result[0] = "error: " + c;
                }
            });
            return result[0];
        } catch (Exception e) {
            log("open error: " + e.getMessage());
            return "error: " + e.getMessage();
        }
    }

    private static String getOpenPath() {
        log("getpath requested");
        try {
            Object wnd = getActiveWindow();
            if (wnd == null) return "error: no active window";

            Object view = wnd.getClass().getMethod("getWorksheetView").invoke(wnd);
            if (view == null) return "error: no view";

            // viewFilePath is private - use reflection
            java.lang.reflect.Field f = view.getClass().getDeclaredField("viewFilePath");
            f.setAccessible(true);
            String path = (String) f.get(view);
            log("getpath: " + path);
            return path != null ? path : "error: no path";
        } catch (Exception e) {
            log("getpath error: " + e.getMessage());
            return "error: " + e.getMessage();
        }
    }

    private static String reload(String filePath) {
        log("reload requested: " + filePath);
        try {
            Class<?> wmiClass = Class.forName("com.maplesoft.worksheet.application.WmiWorksheet");
            Object instance = wmiClass.getMethod("getInstance").invoke(null);
            Object mgr = instance.getClass().getMethod("getWorksheetManager").invoke(instance);

            boolean isOpen = (boolean) mgr.getClass()
                .getMethod("isFileOpen", String.class).invoke(mgr, filePath);
            if (!isOpen) { log("not open"); return "error: not open"; }

            Object wnd = mgr.getClass()
                .getMethod("getWorksheetIfOpen", String.class).invoke(mgr, filePath);
            Object view = wnd.getClass()
                .getMethod("getViewOfFile", String.class).invoke(wnd, filePath);
            if (view == null) { log("no view"); return "error: no view"; }
            log("got view: " + view.getClass().getName());

            String contents = new String(
                java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(filePath)), "UTF-8");
            log("read file: " + contents.length() + " chars");

            final Object fView = view;
            final String fContents = contents;
            final String[] result = {"pending"};

            javax.swing.SwingUtilities.invokeAndWait(() -> {
                try {
                    // Begin undo group so Ctrl+Z undoes the whole edit
                    Object model = fView.getClass().getMethod("getModel").invoke(fView);
                    model.getClass().getMethod("startUndoableEdit", String.class)
                        .invoke(model, "MCP Edit");
                    log("undo: startUndoableEdit");

                    Class<?> loader = Class.forName(
                        "com.maplesoft.worksheet.controller.file.WmiWorksheetFileLoader");

                    Class<?> viewClass = null;
                    for (Class<?> c = fView.getClass(); c != null; c = c.getSuperclass()) {
                        if (c.getName().contains("WorksheetView")) {
                            viewClass = c;
                            break;
                        }
                    }
                    if (viewClass == null) {
                        viewClass = Class.forName("com.maplesoft.worksheet.view.WmiWorksheetView");
                    }

                    java.lang.reflect.Method loadMethod = loader.getMethod("loadContents",
                        String.class, boolean.class, boolean.class,
                        boolean.class, boolean.class, viewClass);

                    loadMethod.invoke(null, fContents, true, false, false, false, fView);

                    // End undo group
                    model.getClass().getMethod("endUndoableEdit").invoke(model);
                    log("undo: endUndoableEdit");

                    result[0] = "ok";
                    log("reload complete (undo-able)!");

                } catch (Exception e) {
                    log("EDT error: " + e.getMessage());
                    if (e.getCause() != null) log("  cause: " + e.getCause());
                    result[0] = "error: " + e.getMessage();
                }
            });

            return result[0];
        } catch (Exception e) {
            log("error: " + e.getMessage());
            return "error: " + e.getMessage();
        }
    }
}
