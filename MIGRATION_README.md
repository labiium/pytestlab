# PyTestLab Migration Resources

This directory contains comprehensive resources to help you migrate from PyTestLab's async API to the new synchronous API.

## 📁 Migration Files

### Documentation
- **[MIGRATION_GUIDE.md](MIGRATION_GUIDE.md)** - Complete step-by-step migration guide
- **[MIGRATION_README.md](MIGRATION_README.md)** - This file

### Tools
- **[scripts/migrate_async_to_sync.py](scripts/migrate_async_to_sync.py)** - Automated migration script

### Examples
- **[examples/migration_example_before.py](examples/migration_example_before.py)** - Async code examples
- **[examples/migration_example_after.py](examples/migration_example_after.py)** - Converted sync examples

## 🚀 Quick Start

### 1. Read the Migration Guide
Start with the comprehensive [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) which covers:
- API changes overview
- Step-by-step migration process
- Common patterns and examples
- Performance considerations
- Testing strategies

### 2. Use the Migration Script
The automated script can handle basic transformations:

```bash
# Migrate a single file (creates backup)
python scripts/migrate_async_to_sync.py my_experiment.py

# Migrate multiple files
python scripts/migrate_async_to_sync.py experiments/*.py

# Dry run to see what would change
python scripts/migrate_async_to_sync.py --dry-run my_code.py
```

### 3. Study the Examples
Compare the before/after examples to understand the patterns:
- `migration_example_before.py` - Original async patterns
- `migration_example_after.py` - Converted sync patterns

## 📋 Migration Checklist

Use this checklist to ensure complete migration:

### Code Changes
- [ ] Remove `import asyncio` statements
- [ ] Convert `async def` to `def`
- [ ] Change `async with await` to `with`
- [ ] Remove all `await` keywords
- [ ] Replace `asyncio.run()` with direct calls
- [ ] Update pytest decorators (`@pytest.mark.asyncio` → none)

### Testing
- [ ] Run automated migration script
- [ ] Review all warnings from migration script
- [ ] Test with simulation mode first
- [ ] Run full test suite
- [ ] Verify performance meets requirements
- [ ] Test with actual hardware

### Documentation
- [ ] Update code comments
- [ ] Update docstrings
- [ ] Update README files
- [ ] Update example code

## ⚡ Key API Changes

### Before (Async)
```python
import asyncio
import pytestlab

async def main():
    async with await pytestlab.Bench.open("config.yaml") as bench:
        result = await bench.dmm.measure_voltage_dc()
        await bench.psu.channel(1).set_voltage(5.0)

asyncio.run(main())
```

### After (Sync)
```python
import pytestlab

def main():
    with pytestlab.Bench.open("config.yaml") as bench:
        result = bench.dmm.measure_voltage_dc()
        bench.psu.channel(1).set_voltage(5.0)

main()
```

## 🛠️ Migration Script Features

The `migrate_async_to_sync.py` script automatically handles:

- ✅ Removes `asyncio` imports
- ✅ Converts `async def` to `def`
- ✅ Updates context managers
- ✅ Removes `await` keywords
- ✅ Replaces `asyncio.run()` calls
- ✅ Updates pytest decorators
- ⚠️ Identifies manual review areas

## 📊 Performance Considerations

### What You Gain
- Simplified code structure
- Better debugging experience
- Improved IDE support
- Reduced memory overhead

### Optimization Tips
- Use batch operations when available
- Leverage connection pooling
- Optimize measurement sequences
- Use vectorized parameters in sessions

## 🔍 Common Issues & Solutions

### Issue: Missing commas after template literals
**Solution**: The migration script fixes JavaScript syntax errors

### Issue: Remaining `await` keywords
**Solution**: Review warnings from migration script and remove manually

### Issue: Test timeouts
**Solution**: Remove `@pytest.mark.asyncio` decorators

### Issue: Performance degradation
**Solution**: Use batch operations and optimize measurement sequences

## 📞 Getting Help

1. **Check the Migration Guide**: Comprehensive patterns and examples
2. **Use Simulation Mode**: Test changes safely with `simulate=True`
3. **Review Script Warnings**: Address all warnings from migration script
4. **Test Incrementally**: Migrate and test one module at a time
5. **Open GitHub Issues**: For complex migration scenarios

## 🎯 Best Practices

### During Migration
1. **Backup your code** before running migration script
2. **Start with simulation** to test changes safely
3. **Migrate incrementally** - one module at a time
4. **Test thoroughly** after each migration step
5. **Review all warnings** from the migration script

### After Migration
1. **Update documentation** to reflect sync patterns
2. **Optimize performance** using batch operations
3. **Review error handling** for sync-specific patterns
4. **Train team members** on new API patterns

## 📈 Migration Timeline

### Phase 1: Preparation (1-2 days)
- Read migration guide
- Backup existing code
- Set up test environment

### Phase 2: Automated Migration (1 day)
- Run migration script
- Review warnings
- Fix syntax errors

### Phase 3: Manual Review (2-3 days)
- Address script warnings
- Test critical paths
- Optimize performance

### Phase 4: Validation (1-2 days)
- Full test suite
- Hardware validation
- Performance verification

## 🔗 Additional Resources

- [PyTestLab Documentation](https://pytestlab.readthedocs.io/)
- [API Reference](https://pytestlab.readthedocs.io/en/latest/api/)
- [Examples Repository](examples/)
- [GitHub Issues](https://github.com/labiium/pytestlab/issues)

---

**Need help?** Open an issue on GitHub or review the comprehensive migration guide for detailed assistance.
