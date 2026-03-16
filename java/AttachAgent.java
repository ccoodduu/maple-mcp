import com.sun.tools.attach.VirtualMachine;

public class AttachAgent {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.out.println("Usage: AttachAgent <pid> <agent.jar>");
            return;
        }
        String pid = args[0];
        String agentJar = args[1];

        System.out.println("Attaching to PID " + pid + " with agent " + agentJar);
        VirtualMachine vm = VirtualMachine.attach(pid);
        try {
            vm.loadAgent(agentJar);
            System.out.println("Agent loaded successfully!");
        } finally {
            vm.detach();
        }
    }
}
