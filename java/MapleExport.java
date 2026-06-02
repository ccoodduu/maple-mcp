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
public class MapleExport {
    public static void main(String[] args) {
        if (args.length < 2) {
            System.err.println("usage: MapleExport <in.mw> <out.pdf>");
            System.exit(2);
        }
        try {
            com.maplesoft.worksheet.util.WmiWorksheetExportUtils.exportPDF(args[0], args[1]);
            System.out.println("OK");
            System.exit(0);
        } catch (Throwable t) {
            t.printStackTrace();
            System.exit(1);
        }
    }
}
