from dify_plugin import Plugin, DifyPluginEnv
import sys

# Patch for dify-plugin SDK issue #280
# Tool-only plugins need this to avoid "Trigger provider not found" error
def apply_trigger_factory_patch():
    """
    Patch TriggerFactory to handle tool-only plugins gracefully.
    This prevents "Trigger provider not found" errors when fetching dynamic parameter options.
    """
    print("🔧 Applying TriggerFactory patch...", file=sys.stderr)
    try:
        from dify_plugin.core.trigger_factory import TriggerFactory, _TriggerProviderEntry
        
        _original_get_entry = TriggerFactory._get_entry
        print(f"   Original method: {_original_get_entry}", file=sys.stderr)
        
        def _patched_get_entry(self, provider_name: str):
            try:
                result = _original_get_entry(self, provider_name)
                print(f"   ✅ Found trigger provider: {provider_name}", file=sys.stderr)
                return result
            except (KeyError, ValueError) as e:
                if "not found" in str(e).lower() or isinstance(e, KeyError):
                    # For tool-only plugins, return a minimal valid entry
                    # This allows the SDK to continue and fall back to Tool's _fetch_parameter_options
                    print(f"   ⚠️  Trigger provider '{provider_name}' not found - returning empty entry (tool-only plugin)", file=sys.stderr)
                    return _TriggerProviderEntry(
                        configuration=None,
                        provider_cls=None,
                        subscription_constructor_cls=None,
                        events={}
                    )
                raise
        
        TriggerFactory._get_entry = _patched_get_entry
        print(f"   Patched method: {TriggerFactory._get_entry}", file=sys.stderr)
        print("✅ TriggerFactory patch applied successfully", file=sys.stderr)
        
    except Exception as e:
        print(f"❌ TriggerFactory patch failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)

# Apply the patch before creating the plugin instance
apply_trigger_factory_patch()

print("🚀 Creating Plugin instance...", file=sys.stderr)
plugin = Plugin(DifyPluginEnv(MAX_REQUEST_TIMEOUT=120))
print("✅ Plugin instance created", file=sys.stderr)

if __name__ == '__main__':
    plugin.run()
