import { useMediaQuery } from "./useMediaQuery";
import { useWorkerGlobalContext } from "./components/WorkerGlobalContext";
import { AppFrame } from "./components/shell/AppFrame";
import { useAppNavigation, useCommandPalette } from "./components/shell/useAppNavigation";
import { useCompactNavigation } from "./components/shell/useCompactNavigation";
import { useConversationDirectory } from "./components/shell/useConversationDirectory";

export function App() {
  const phone = useMediaQuery("(max-width: 640px)");
  const compactNavigation = useMediaQuery("(max-width: 760px)");
  const { identity } = useWorkerGlobalContext();
  const directory = useConversationDirectory();
  const rail = useCompactNavigation(compactNavigation);
  const navigation = useAppNavigation({
    closeNavigation: rail.closeNavigation,
    refreshConversations: directory.refresh,
  });
  const palette = useCommandPalette(rail.closeNavigation, navigation.chooseDestination);

  return (
    <AppFrame
      directory={directory}
      identity={identity}
      navigation={navigation}
      palette={palette}
      phone={phone}
      rail={rail}
    />
  );
}
