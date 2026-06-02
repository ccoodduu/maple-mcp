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
