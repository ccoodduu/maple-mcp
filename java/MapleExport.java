// Standalone launcher that renders a Maple .mw document to PDF using Maple's
// own GUI export pipeline (the same path as File > Export As > PDF).
//
// It parses the .mw from disk into a fresh in-memory model, so it does NOT
// touch (or require) the user's open Maple window — it works even if Maple is
// closed. Run inside Maple's bundled JVM with the full java/ classpath:
//
//   java -Djava.library.path=<MAPLE>/bin.X86_64_WINDOWS \
//        -cp "<MAPLE>/java/*;maple-export.jar" MapleExport <in.mw> <out.pdf>
//
// Must run NON-headless: the PDF formatter constructs (invisible) Swing owner
// frames internally and throws HeadlessException under -Djava.awt.headless=true.
//
// Maple's export API is resolved REFLECTIVELY, exactly like ReloadAgent does.
// That keeps this jar free of any compile-time link against a specific Maple's
// worksheet.jar, so ONE jar serves every Maple version and the build needs no
// -cp. When a future Maple moves or renames the API, the failure is a readable
// message naming the missing class/method instead of a NoClassDefFoundError.
//
//   javac -d _b java/MapleExport.java        # no Maple classpath required
//   jar cfe maple-export.jar MapleExport -C _b MapleExport.class
//
// PROBE MODE checks the WHOLE private-API surface this project depends on —
// both this launcher's export call and every class ReloadAgent reaches by
// reflection. Maplesoft guarantees .mw file compatibility; it guarantees
// nothing about com.maplesoft.* internals, so this is the cheapest possible
// first check when porting to a new Maple. It only resolves classes and
// members, so it needs NO licence and NO desktop session:
//
//   java -cp "<MAPLE>/java/*;maple-export.jar" MapleExport --probe
//
// Exit 0 = every required member resolved. Exit 1 = something moved; each line
// says whether the class vanished, the signature changed, or only the
// parameter types differ.

import java.lang.reflect.Constructor;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

public class MapleExport {
    private static final String EXPORT_CLASS =
            "com.maplesoft.worksheet.util.WmiWorksheetExportUtils";
    private static final String EXPORT_METHOD = "exportPDF";

    // The private Maple API this project binds to. Format:
    //   fully.qualified.Class                       (class must exist)
    //   fully.qualified.Class#method(argType,...)   (method must exist)
    //   fully.qualified.Class#<init>(argType,...)   (constructor must exist)
    // Keep in sync with java/ReloadAgent.java — tests/test_probe_manifest.py
    // fails if ReloadAgent reflects on a class that is missing from this list.
    private static final String[] REQUIRED = {
        // --- this launcher -------------------------------------------------
        "com.maplesoft.worksheet.util.WmiWorksheetExportUtils#exportPDF(java.lang.String,java.lang.String)",
        // --- ReloadAgent: save / getpath / reload --------------------------
        "com.maplesoft.worksheet.application.WmiWorksheet#getInstance()",
        "com.maplesoft.worksheet.view.WmiWorksheetView",
        "com.maplesoft.worksheet.controller.file.WmiWorksheetFileLoader"
            + "#loadContents(java.lang.String,boolean,boolean,boolean,boolean,"
            + "com.maplesoft.worksheet.view.WmiWorksheetView)",
        // --- ReloadAgent: evalnew (run_executable) -------------------------
        "com.maplesoft.mathdoc.model.WmiModel#getDocument()",
        "com.maplesoft.mathdoc.model.WmiModelLock#writeLock(com.maplesoft.mathdoc.model.WmiModel,boolean)",
        "com.maplesoft.mathdoc.model.WmiModelLock#writeUnlock(com.maplesoft.mathdoc.model.WmiModel)",
        "com.maplesoft.mathdoc.model.WmiModelSearcher"
            + "#visitDepthFirst(com.maplesoft.mathdoc.model.WmiModel,com.maplesoft.util.WmiSearchVisitor)",
        "com.maplesoft.util.WmiSearchVisitor",
        "com.maplesoft.worksheet.controller.WmiExecutionVisitor#<init>()",
        "com.maplesoft.worksheet.controller.WmiExecutionVisitor#getExecutionGroups()",
        "com.maplesoft.worksheet.controller.edit.WmiExecuteGroups#<init>(java.util.List)",
        "com.maplesoft.worksheet.controller.edit.WmiExecuteGroups#start()",
        "com.maplesoft.worksheet.model.WmiExecutionGroupModel"
            + "#isAnythingExecutingInDocument(com.maplesoft.mathdoc.model.WmiMathDocumentModel)",
        "com.maplesoft.mathdoc.model.WmiMathDocumentModel",
    };

    // Members ReloadAgent resolves off a LIVE object, whose class is only known
    // once Maple is running. A static probe cannot reach them; listed so the
    // gap is visible rather than mistaken for full coverage.
    private static final String[] RUNTIME_ONLY = {
        "getWorksheetManager()        on the WmiWorksheet singleton",
        "getActiveWindow()            on the worksheet manager",
        "isFileOpen(String)           on the worksheet manager",
        "getWorksheetIfOpen(String)   on the worksheet manager",
        "saveWindowContents()         on the worksheet window",
        "getWorksheetView()           on the worksheet window",
        "getViewOfFile(String)        on the worksheet window",
        "getModel()                   on the worksheet view",
        "viewFilePath (private field) on the worksheet view",
        "startUndoableEdit(String)    on the document model",
        "endUndoableEdit()            on the document model",
        "getOutput()                  on each execution group",
        "canExecute()                 on each execution group",
    };

    public static void main(String[] args) {
        if (args.length == 1 && args[0].equals("--probe")) {
            System.exit(probe());
        }
        if (args.length < 2) {
            System.err.println("usage: MapleExport <in.mw> <out.pdf>");
            System.err.println("       MapleExport --probe");
            System.exit(2);
        }
        try {
            resolveExport().invoke(null, args[0], args[1]);
            System.out.println("OK");
            System.exit(0);
        } catch (InvocationTargetException ite) {
            // Unwrap: maple_render.py surfaces the FIRST Exception/Error line as the
            // cause, and it sniffs that text for HeadlessException / "no screen
            // device". A bare InvocationTargetException would mask both.
            Throwable cause = ite.getCause() != null ? ite.getCause() : ite;
            cause.printStackTrace();
            System.exit(1);
        } catch (Throwable t) {
            t.printStackTrace();
            System.exit(1);
        }
    }

    private static Method resolveExport() throws Exception {
        Class<?> util;
        try {
            util = Class.forName(EXPORT_CLASS);
        } catch (ClassNotFoundException e) {
            throw new IllegalStateException(
                    "Maple export API Error: class " + EXPORT_CLASS + " is not on the "
                    + "classpath. Either -cp is missing <MAPLE>/java/*, or this Maple "
                    + "version moved/renamed the export API.");
        }
        try {
            return util.getMethod(EXPORT_METHOD, String.class, String.class);
        } catch (NoSuchMethodException e) {
            throw new IllegalStateException(
                    "Maple export API Error: " + EXPORT_CLASS + "." + EXPORT_METHOD
                    + "(String, String) not found — the signature changed in this Maple "
                    + "version. Candidates present: " + candidates(util));
        }
    }

    private static String candidates(Class<?> util) {
        List<String> found = new ArrayList<>();
        for (Method m : util.getMethods()) {
            if (!m.getName().toLowerCase().contains("export")) {
                continue;
            }
            found.add(m.getName() + "(" + types(m.getParameterTypes()) + ")");
        }
        return found.isEmpty() ? "(none)" : String.join(", ", found);
    }

    private static String types(Class<?>[] ps) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < ps.length; i++) {
            if (i > 0) {
                sb.append(", ");
            }
            sb.append(ps[i].getSimpleName());
        }
        return sb.toString();
    }

    private static Class<?> resolveType(String name) throws ClassNotFoundException {
        switch (name) {
            case "boolean": return boolean.class;
            case "int":     return int.class;
            case "long":    return long.class;
            case "double":  return double.class;
            default:        return Class.forName(name);
        }
    }

    /** "ok" when the member resolves; otherwise a short reason. */
    private static String checkSpec(String spec) {
        int hash = spec.indexOf('#');
        String className = hash < 0 ? spec : spec.substring(0, hash);
        Class<?> c;
        try {
            c = Class.forName(className);
        } catch (Throwable t) {
            return "CLASS MISSING";
        }
        if (hash < 0) {
            return "ok";
        }

        String member = spec.substring(hash + 1);
        int paren = member.indexOf('(');
        String name = member.substring(0, paren);
        String argList = member.substring(paren + 1, member.length() - 1).trim();
        String[] argNames = argList.isEmpty() ? new String[0] : argList.split(",");
        Class<?>[] args = new Class<?>[argNames.length];
        for (int i = 0; i < argNames.length; i++) {
            try {
                args[i] = resolveType(argNames[i].trim());
            } catch (Throwable t) {
                return "PARAM TYPE MISSING: " + argNames[i].trim();
            }
        }

        if (name.equals("<init>")) {
            try {
                c.getConstructor(args);
                return "ok";
            } catch (NoSuchMethodException ignored) {
                // ReloadAgent also uses getDeclaredConstructor for the no-arg case.
            }
            try {
                c.getDeclaredConstructor(args);
                return "ok";
            } catch (NoSuchMethodException ignored) {
                // fall through to arity search
            }
            for (Constructor<?> k : c.getDeclaredConstructors()) {
                if (k.getParameterCount() == args.length) {
                    return "SIGNATURE CHANGED: <init>(" + types(k.getParameterTypes()) + ")";
                }
            }
            return "CONSTRUCTOR MISSING";
        }

        try {
            c.getMethod(name, args);
            return "ok";
        } catch (NoSuchMethodException ignored) {
            // fall through
        }
        // Same name and arity but different parameter types: the call may still
        // work at runtime (ReloadAgent passes some types it discovers live), so
        // report it as a warning rather than a hard miss.
        String byArity = null;
        boolean nameExists = false;
        for (Method m : c.getMethods()) {
            if (!m.getName().equals(name)) {
                continue;
            }
            nameExists = true;
            if (m.getParameterCount() == args.length) {
                byArity = "PARAM TYPES DIFFER: " + name + "(" + types(m.getParameterTypes()) + ")";
            }
        }
        if (byArity != null) {
            return byArity;
        }
        if (nameExists) {
            return "ARITY CHANGED: " + name + " exists with a different parameter count";
        }
        return "METHOD MISSING";
    }

    // Resolution only — never invokes anything, so it needs no licence and no
    // desktop session. Exit 0 = this Maple is compatible.
    private static int probe() {
        System.out.println("java.version=" + System.getProperty("java.version"));
        System.out.println("Checking " + REQUIRED.length + " required members of Maple's private API");
        System.out.println();

        int bad = 0, warn = 0;
        for (String spec : REQUIRED) {
            String status = checkSpec(spec);
            String label = spec.replace("com.maplesoft.", "~.");
            if (status.equals("ok")) {
                System.out.println("  ok       " + label);
            } else if (status.startsWith("PARAM TYPES DIFFER")) {
                warn++;
                System.out.println("  WARN     " + label);
                System.out.println("           " + status);
            } else {
                bad++;
                System.out.println("  FAILED   " + label);
                System.out.println("           " + status);
            }
        }

        System.out.println();
        System.out.println("Not statically checkable (resolved off live objects at runtime):");
        for (String r : RUNTIME_ONLY) {
            System.out.println("  ?        " + r);
        }
        System.out.println("  -> these only fail once Maple is running; run the MCP's");
        System.out.println("     save / reload / run_executable paths to cover them.");

        System.out.println();
        if (bad > 0) {
            System.out.println("PROBE FAILED: " + bad + " member(s) moved, " + warn + " warning(s)");
            return 1;
        }
        System.out.println("PROBE OK: all " + REQUIRED.length + " resolved"
                + (warn > 0 ? ", " + warn + " warning(s)" : ""));
        return 0;
    }
}
